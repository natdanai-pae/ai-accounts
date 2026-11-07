"""Windows desktop client; all account mutations go through the private helper."""
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

def date(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None

def number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)

def recommendation(usage, now=None):
    if usage.get('error'):
        return None, 'Quota refresh failed'
    now = now or datetime.now(timezone.utc)
    updated = date(usage.get('updatedAt'))
    if not updated or not 0 <= (now - updated).total_seconds() <= 900:
        return None, 'Refresh quota: missing or stale timestamp'
    scores = []
    for name in ('secondary', 'primary') if 'primary' in usage else ('secondary',):
        window = usage.get(name) or {}
        used, reset = window.get('usedPercent'), date(window.get('resetsAt'))
        if not number(used) or not 0 <= used < 100 or not reset or reset <= now:
            return None, 'Unknown, exhausted or expired quota'
        scores.append((100 - used) / max((reset - now).total_seconds() / 3600, 1 / 60))
    return min(scores), 'Remaining % per hour until reset; limited by primary window'

def parse_accounts(data):
    rows = data.get('accounts')
    if not isinstance(rows, list):
        raise ValueError('Invalid account list')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get('provider') not in ('codex', 'claude') or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', row.get('key', '')) or row.get('id') != row['provider'] + ':' + row['key'] or row['id'] in seen:
            raise ValueError('Invalid or duplicate account')
        seen.add(row['id'])
    return rows

def match_usage(account, rows):
    matches = []
    for row in rows:
        if not isinstance(row, dict) or row.get('error') or row.get('provider') != account['provider'] or not isinstance(row.get('usage'), dict):
            continue
        usage = row['usage']
        matches_id = usage.get('accountEmail') == account['email'] if account.get('email') else bool(account.get('usageAccount')) and row.get('account') == account['usageAccount']
        if matches_id:
            matches.append(usage)
    return max(matches, key=lambda u: date(u.get('updatedAt')) or datetime.min.replace(tzinfo=timezone.utc)) if matches else None

def stable_numbers(accounts, saved):
    legacy = {'codex:main': 1, 'codex:account2': 2, 'codex:account3': 3, 'claude:a': 1, 'claude:b': 2, 'claude:c': 3}
    result = {}
    for provider in ('codex', 'claude'):
        used = set()
        keys = sorted(set(k for k in saved if re.fullmatch(provider + r':[A-Za-z0-9_-]{1,128}', k)), key=lambda k: (legacy.get(k, 1000000000), k))
        for key in keys:
            value = saved[key]
            if isinstance(value, int) and not isinstance(value, bool) and 0 < value < 1000000000 and value not in used:
                result[key] = value
                used.add(value)
        keys = sorted({a['id'] for a in accounts if a['provider'] == provider}, key=lambda k: (legacy.get(k, 1000000000), k))
        for key in keys:
            if key not in result:
                value = legacy.get(key, 1)
                while value in used:
                    value += 1
                result[key] = value
                used.add(value)
    return result

def ordered_accounts(accounts, mapping):
    return sorted(accounts, key=lambda a: (a['provider'], mapping[a['id']], a['id']))

def provider_winner(accounts, values, provider, now=None):
    eligible = [(a, recommendation(values[a['id']], now)[0]) for a in accounts if a['provider'] == provider and values.get(a['id'])]
    eligible = [(a, score) for a, score in eligible if score is not None]
    return sorted(eligible, key=lambda item: (-item[1], item[0]['id']))[0][0] if eligible else None

def alert_policy(saved, accounts, values, now, enabled):
    stamp = now.timestamp()
    state = {'winners': dict(saved.get('winners', {})), 'lastAlert': dict(saved.get('lastAlert', {})),
             'events': {k: v for k, v in saved.get('events', {}).items() if number(v) and v > stamp}}
    alerts = []
    for provider in ('codex', 'claude'):
        winner = provider_winner(accounts, values, provider, now)
        if not winner:
            continue  # Failed/stale refresh never erases the last valid recommendation.
        previous = state['winners'].get(provider)
        state['winners'][provider] = winner['id']
        candidates = []
        if previous and previous != winner['id']:
            candidates.append({'kind': 'winner', 'provider': provider, 'account': winner['id'], 'key': 'winner:' + winner['id'], 'expires': stamp + 86400})
        for account in ordered_accounts(accounts, stable_numbers(accounts, {})):
            usage = values.get(account['id'])
            if account['provider'] != provider or not usage or recommendation(usage, now)[0] is None:
                continue
            names = ('secondary', 'primary') if 'primary' in usage else ('secondary',)
            limiting = min(names, key=lambda name: (100 - usage[name]['usedPercent']) / max((date(usage[name]['resetsAt']) - now).total_seconds(), 60))
            reset = date(usage[limiting]['resetsAt'])
            if 0 < (reset - now).total_seconds() <= 3600:
                candidates.append({'kind': 'reset', 'provider': provider, 'account': account['id'], 'key': 'reset:' + account['id'] + ':' + reset.isoformat(), 'expires': reset.timestamp()})
        last = state['lastAlert'].get(provider)
        if not enabled or (number(last) and stamp - last < 1800):
            continue
        candidate = next((event for event in candidates if event['key'] not in state['events']), None)
        if candidate:
            state['events'][candidate['key']] = candidate['expires']
            state['lastAlert'][provider] = stamp
            alerts.append(candidate)
    return state, alerts

def refresh_due(last, now, busy):
    return not busy and (now < last or now - last >= 300)

def reset_text(value, now=None):
    reset = date(value)
    if not reset:
        return 'ไม่ทราบเวลารีเซ็ต'
    seconds = (reset - (now or datetime.now(timezone.utc))).total_seconds()
    absolute = reset.astimezone().strftime('%d/%m %H:%M')
    if seconds <= 0:
        return 'ถึงเวลารีเซ็ตแล้ว • รีเฟรชข้อมูล'
    minutes = math.ceil(seconds / 60)
    countdown = f'{minutes // 60} ชม. {minutes % 60} นาที' if minutes >= 60 else f'{minutes} นาที'
    return f'รีเซ็ตอีก {countdown} ({absolute})'

def main():
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog
    root = tk.Tk()
    root.title('AI Accounts • Windows beta')
    root.geometry('1120x850')
    root.minsize(940, 680)
    colors = {'base': '#EEF3F7', 'card': '#FFFFFF', 'ink': '#193044', 'muted': '#526779', 'teal': '#096B63', 'tint': '#DDF1EC'}
    root.configure(background=colors['base'])
    root.option_add('*Font', ('Leelawadee UI', 10))
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Leelawadee UI', 10), background=colors['base'], foreground=colors['ink'])
    style.configure('TButton', padding=(12, 7), background='#FFFFFF')
    style.map('TButton', background=[('active', '#DDE8EF')])
    style.configure('Accent.TButton', foreground='white', background=colors['teal'])
    style.map('Accent.TButton', background=[('active', '#075A53')])
    style.configure('Card.TFrame', background=colors['card'])
    style.configure('Card.TLabel', background=colors['card'])
    style.configure('Muted.TLabel', foreground=colors['muted'])
    style.configure('CardMuted.TLabel', background=colors['card'], foreground=colors['muted'])
    style.configure('Ribbon.TFrame', background=colors['tint'])
    style.configure('Ribbon.TLabel', background=colors['tint'], foreground=colors['teal'])
    style.configure('Quota.Horizontal.TProgressbar', background=colors['teal'], troughcolor='#E2EBEF', borderwidth=0, thickness=8)
    smoke = '--self-test' in sys.argv
    if smoke:
        root.withdraw()
        assert recommendation({'updatedAt': None})[0] is None
    resources = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    helper = resources / 'backend/aiaccounts-helper.exe'
    icon = resources / 'assets/AppIcon.png'
    if icon.exists():
        root._icon = tk.PhotoImage(file=str(icon))
        root.iconphoto(True, root._icon)
    events = queue.Queue()
    state = {'busy': False, 'accounts': [], 'usage': {}, 'lastRefresh': 0, 'lastPaint': 0}
    private_dir = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'AI Accounts'
    preferences_path = private_dir / 'ui-preferences.json'
    preferences = {'numbers': {}, 'alerts': {}, 'notifications': False}
    try:
        from backend import read_json
        if preferences_path.is_symlink():
            raise ValueError()
        loaded = {} if smoke else read_json(preferences_path, {})
        if isinstance(loaded.get('numbers'), dict):
            preferences['numbers'] = loaded['numbers']
        if isinstance(loaded.get('alerts'), dict) and all(isinstance(loaded['alerts'].get(k, {}), dict) for k in ('winners', 'events', 'lastAlert')):
            preferences['alerts'] = loaded['alerts']
        preferences['notifications'] = loaded.get('notifications') is True
    except Exception:
        pass
    notifications = tk.BooleanVar(value=preferences['notifications'])
    toolbar = ttk.Frame(root, padding=(20, 14, 20, 8))
    toolbar.pack(fill='x')
    ttk.Label(toolbar, text='AI Accounts', font=('Leelawadee UI', 21, 'bold')).pack(side='left')
    ttk.Label(toolbar, text='เลือกบัญชีให้เหมาะกับโควตาที่เหลือ', style='Muted.TLabel').pack(side='left', padx=18)
    status = tk.StringVar(value='กำลังอ่านบัญชี…')
    actions = ttk.Frame(root, padding=(20, 0, 20, 8))
    actions.pack(fill='x')
    notice = tk.StringVar(value='แจ้งในแอปและเสียง: ' + ('เปิด' if notifications.get() else 'ปิด') + ' • ไม่มี Windows toast • รีเฟรชทุก 5 นาทีขณะเปิดแอป')
    ttk.Label(root, textvariable=notice, foreground=colors['teal'], wraplength=1050, padding=(20, 6, 20, 8)).pack(fill='x')
    columns = ttk.Frame(root, padding=(14, 0, 14, 0))
    columns.pack(fill='both', expand=True)
    panels, ribbons, scroll_surfaces = {}, {}, []
    for provider in ('codex', 'claude'):
        column = 0 if provider == 'codex' else 1
        columns.columnconfigure(column, weight=1, uniform='providers')
        columns.rowconfigure(0, weight=1)
        pane = ttk.Frame(columns, padding=6)
        pane.grid(row=0, column=column, sticky='nsew')
        heading = ttk.Frame(pane)
        heading.pack(fill='x', pady=(2, 8))
        ttk.Label(heading, text=provider.title(), font=('Leelawadee UI', 17, 'bold')).pack(side='left')
        ttk.Button(heading, text='+ เพิ่มบัญชี', command=lambda p=provider: add(p)).pack(side='right')
        ribbon = ttk.Frame(pane, style='Ribbon.TFrame', padding=14)
        ribbon.pack(fill='x', pady=(0, 10))
        ribbons[provider] = ribbon
        canvas = tk.Canvas(pane, highlightthickness=0, width=450, background=colors['base'])
        scroll = ttk.Scrollbar(pane, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        rows = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=rows, anchor='nw')
        rows.bind('<Configure>', lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
        canvas.bind('<Configure>', lambda e, c=canvas, w=window: c.itemconfigure(w, width=e.width))
        panels[provider] = rows
        scroll_surfaces.append((pane, canvas))

    def mousewheel(event):
        for pane, canvas in scroll_surfaces:
            if str(event.widget).startswith(str(pane) + '.'):
                canvas.yview_scroll(-int(event.delta / 120), 'units')
                return 'break'
    root.bind('<MouseWheel>', mousewheel)

    def invoke(args):
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        timeout = 900 if args[0] == 'usage' else 650 if args[0] == 'add' else 180
        result = subprocess.run([str(helper), *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, creationflags=flags)
        if len(result.stdout) > 8 * 1024 * 1024:
            raise ValueError()
        data = json.loads(result.stdout)
        if isinstance(data, dict) and data.get('ok') is False:
            # Only helper-owned SafeError messages cross this boundary.
            raise RuntimeError(str(data.get('message', 'Operation failed safely'))[:300])
        if result.returncode and not isinstance(data, list):
            raise ValueError()
        return data

    def work(args):
        if state['busy']:
            return
        state['busy'] = True
        state['lastRefresh'] = time.time()
        status.set('กำลังทำงาน… หากมีหน้าต่างเข้าสู่ระบบ ให้ทำขั้นตอนให้เสร็จและเปิดแอปนี้ไว้')
        def run():
            try:
                result = invoke(args)
                accounts = parse_accounts(invoke(['list']))
                usage = {}
                for provider in ('codex', 'claude'):
                    try:
                        value = invoke(['usage', provider])
                        usage[provider] = value if isinstance(value, list) else []
                    except Exception:
                        usage[provider] = []
                events.put((accounts, usage, result.get('message', 'Updated') if isinstance(result, dict) else 'Updated'))
            except RuntimeError as error:
                events.put((None, None, str(error)))
            except Exception:
                events.put((None, None, 'Operation failed safely. Check installed provider apps and login, then retry.'))
        threading.Thread(target=run, daemon=True).start()

    def switch(account):
        if state['busy']:
            return
        if messagebox.askokcancel('สลับบัญชี', 'บันทึกงานก่อนสลับ และปิดหน้าต่าง Codex เองก่อนสลับ Codex\n\nสลับไป ' + account_title(account) + '?', parent=root):
            work(['switch', account['provider'], account['key']])

    def add(provider):
        if state['busy']:
            return
        label = simpledialog.askstring('เพิ่มบัญชี ' + provider.title(), 'ชื่อบัญชี (ขั้นต่อไปจะเปิดหน้าต่างเข้าสู่ระบบตามปกติ):', parent=root)
        if label:
            work(['add', provider, label])

    def save_preferences():
        from backend import atomic_json
        try:
            if preferences_path.is_symlink():
                raise ValueError()
            atomic_json(preferences_path, preferences)
        except Exception:
            status.set('บันทึกเลขบัญชีหรือการแจ้งเตือนไม่สำเร็จ • การตั้งค่านี้อาจไม่คงอยู่เมื่อเปิดใหม่')

    def account_title(account):
        return account['provider'].title() + ' บัญชี ' + str(preferences['numbers'].get(account['id'], '?'))

    def values_by_account():
        return {a['id']: match_usage(a, state['usage'].get(a['provider'], [])) for a in state['accounts']}

    def details(account, usage):
        lines = [account_title(account), str(account.get('label') or ''), account.get('email') or 'ยังไม่เชื่อมข้อมูลตัวตน']
        if usage:
            for key, label in (('secondary', 'รายสัปดาห์'), ('primary', 'รอบหลัก')):
                if key in usage:
                    window = usage[key] or {}
                    used = window.get('usedPercent')
                    lines.extend([label + ': เหลือ ' + (f'{100-used:g}%' if number(used) and 0 <= used <= 100 else 'ไม่ทราบ'), reset_text(window.get('resetsAt'))])
            source = next((r for r in state['usage'].get(account['provider'], []) if isinstance(r, dict) and r.get('usage') is usage), {})
            cost = usage.get('providerCost') or {}
            balance = (source.get('credits') or {}).get('remaining') if account['provider'] == 'codex' else cost.get('balance')
            available = (source.get('resetCredits') or {}).get('available')
            lines.extend(['เครดิต: ' + (str(balance) + ' ' + str(cost.get('currencyCode', '')) if number(balance) else 'ไม่ทราบ'), 'สิทธิ์รีเซ็ต: ' + (str(available) if number(available) else 'ไม่ทราบ'), 'อัปเดต: ' + str(usage.get('updatedAt') or 'ไม่ทราบ')])
        else:
            lines.append('ไม่มีข้อมูลโควตา • เชื่อมโควตาแล้วรีเฟรชอีกครั้ง')
        lines.append('คำแนะนำเทียบเฉพาะผู้ให้บริการเดียวกัน ใช้ % ที่เหลือต่อชั่วโมงจนรีเซ็ต โดยจำกัดด้วยรอบหลัก ไม่ใช่จำนวนโทเคน และไม่สลับบัญชีอัตโนมัติ')
        messagebox.showinfo('รายละเอียดบัญชี', '\n\n'.join(lines), parent=root)

    def render():
        state['lastPaint'] = time.time()
        values = values_by_account()
        for provider, panel in panels.items():
            for widget in panel.winfo_children():
                widget.destroy()
            accounts = ordered_accounts([a for a in state['accounts'] if a['provider'] == provider], preferences['numbers'])
            winner = provider_winner(accounts, values, provider)
            ribbon = ribbons[provider]
            for widget in ribbon.winfo_children():
                widget.destroy()
            if winner:
                usage = values[winner['id']]
                week = usage['secondary']
                ttk.Label(ribbon, text='แนะนำตอนนี้: บัญชี ' + str(preferences['numbers'][winner['id']]), style='Ribbon.TLabel', font=('Leelawadee UI', 14, 'bold')).pack(anchor='w')
                ttk.Label(ribbon, text=f'รายสัปดาห์เหลือ {100-week["usedPercent"]:g}%\n' + reset_text(week['resetsAt']), style='Ribbon.TLabel', wraplength=380).pack(anchor='w', pady=5)
                ttk.Label(ribbon, text='เหลือต่อชั่วโมงก่อนรีเซ็ตสูงสุด โดยคำนึงถึงรอบหลัก', style='Ribbon.TLabel', wraplength=380).pack(anchor='w')
                ttk.Button(ribbon, text='ใช้บัญชีนี้', style='Accent.TButton', command=lambda a=winner: switch(a)).pack(anchor='w', pady=(9, 0))
            else:
                ttk.Label(ribbon, text='ยังไม่มีบัญชีที่แนะนำ', style='Ribbon.TLabel', font=('Leelawadee UI', 14, 'bold')).pack(anchor='w')
                ttk.Label(ribbon, text='ต้องมีโควตาคงเหลือและเวลารีเซ็ตที่ตรวจสอบได้\nข้อมูลต้องอัปเดตภายใน 15 นาที', style='Ribbon.TLabel', wraplength=380).pack(anchor='w', pady=6)
            if not accounts:
                ttk.Label(panel, text='เพิ่มบัญชีและเข้าสู่ระบบ\nจากนั้นเชื่อมโควตาและตั้งค่าแชร์เซสชัน', wraplength=380, style='Muted.TLabel').pack(pady=24)
            for account in accounts:
                usage = values.get(account['id'])
                row = ttk.Frame(panel, padding=14, style='Card.TFrame')
                row.pack(fill='x', pady=(0, 10))
                top = ttk.Frame(row, style='Card.TFrame')
                top.pack(fill='x')
                ttk.Label(top, text='บัญชี ' + str(preferences['numbers'][account['id']]), style='Card.TLabel', font=('Leelawadee UI', 13, 'bold')).pack(side='left')
                if winner and winner['id'] == account['id']:
                    ttk.Label(top, text='แนะนำ', style='Card.TLabel', foreground=colors['teal']).pack(side='right')
                ttk.Label(row, text=account.get('label') or account['key'], style='CardMuted.TLabel', wraplength=380).pack(anchor='w', pady=(2, 8))
                detail = 'ไม่มีข้อมูลโควตา • เชื่อมโควตาหรือรีเฟรช'
                if usage:
                    week = usage.get('secondary') or {}
                    used = week.get('usedPercent')
                    fresh = date(usage.get('updatedAt'))
                    fresh = fresh is not None and 0 <= (datetime.now(timezone.utc) - fresh).total_seconds() <= 900
                    if number(used) and 0 <= used <= 100:
                        ttk.Label(row, text=f'รายสัปดาห์เหลือ {100-used:g}%' + ('' if fresh else ' • ข้อมูลเก่า'), style='Card.TLabel').pack(anchor='w')
                        ttk.Progressbar(row, style='Quota.Horizontal.TProgressbar', maximum=100, value=100-used).pack(fill='x', pady=7)
                    detail = reset_text(week.get('resetsAt'))
                    if recommendation(usage)[0] is None:
                        detail += '\nยังไม่ใช้แนะนำ: โควตาหมด ข้อมูลเก่า หรือข้อมูลไม่ครบ'
                ttk.Label(row, text=detail, wraplength=380, style='CardMuted.TLabel').pack(anchor='w', pady=(0, 9))
                buttons = ttk.Frame(row, style='Card.TFrame')
                buttons.pack(fill='x')
                ttk.Button(buttons, text='สลับบัญชี', command=lambda a=account: switch(a)).pack(side='left')
                ttk.Button(buttons, text='รายละเอียด', command=lambda a=account, u=usage: details(a, u)).pack(side='right')

    def poll():
        try:
            accounts, usage, message = events.get_nowait()
            state['busy'] = False
            if accounts is not None:
                state.update(accounts=accounts, usage=usage)
                preferences['numbers'] = stable_numbers(accounts, preferences['numbers'])
                preferences['alerts'], alerts = alert_policy(preferences['alerts'], accounts, values_by_account(), datetime.now(timezone.utc), notifications.get())
                render()
                for alert in alerts:
                    account = next(a for a in accounts if a['id'] == alert['account'])
                    text = account_title(account) + (' เป็นบัญชีที่แนะนำใหม่' if alert['kind'] == 'winner' else ' มีโควตาเหลือและจะรีเซ็ตภายใน 60 นาที')
                    notice.set(text + ' • ไม่มีการสลับอัตโนมัติ')
                    if os.name == 'nt':
                        try:
                            import winsound
                            winsound.MessageBeep(winsound.MB_ICONASTERISK)
                        except RuntimeError:
                            pass
                save_preferences()
            status.set(message)
        except queue.Empty:
            pass
        root.after(100, poll)

    def sync_sessions():
        if not state['busy']:
            state['busy'] = True
            def run_sync():
                try:
                    invoke(['sync'])
                    events.put((None, None, 'ตรวจการแชร์เซสชันแล้ว • โควตารีเฟรชทุก 5 นาที'))
                except Exception:
                    events.put((None, None, 'Session sync unavailable; open Code for each account and run Setup.'))
            threading.Thread(target=run_sync, daemon=True).start()
        root.after(20000, sync_sessions)

    def refresh_timer():
        if time.time() - state['lastPaint'] >= 60:
            render()
        if refresh_due(state['lastRefresh'], time.time(), state['busy']):
            work(['list'])
        root.after(1000, refresh_timer)

    def notification_toggle():
        preferences['notifications'] = notifications.get()
        save_preferences()
        notice.set(('เปิด' if notifications.get() else 'ปิด') + 'การแจ้งในแอปและเสียง • ไม่มี Windows toast • ไม่สลับบัญชีอัตโนมัติ')

    def notification_help():
        messagebox.showinfo('การแจ้งเตือน', 'ปิดเป็นค่าเริ่มต้น เมื่อเปิดจะแจ้งในแอปและเล่นเสียง Windows\nไม่มีการส่ง Windows toast หรือข้อมูลอีเมล\n\nแจ้งเมื่อบัญชีแนะนำเปลี่ยน หรือรอบที่จำกัดการใช้งานจะรีเซ็ตภายใน 60 นาทีและยังมีโควตา\nเว้นอย่างน้อย 30 นาทีต่อผู้ให้บริการ และจำเหตุการณ์เพื่อไม่แจ้งซ้ำ\nข้อมูลเก่าหรืออ่านไม่สำเร็จจะไม่แจ้งเตือน\n\nรีเฟรชทุก 5 นาทีเฉพาะขณะเปิดแอป ไม่มีการสลับบัญชีอัตโนมัติ', parent=root)

    for title, command in [('รีเฟรช', 'list'), ('เชื่อมโควตา', 'connect'), ('ตั้งค่าแชร์เซสชัน', 'setup')]:
        ttk.Button(actions, text=title, command=lambda c=command: work([c])).pack(side='left', padx=(0, 6))
    ttk.Button(actions, text='วิธีแจ้งเตือน', command=notification_help).pack(side='right')
    ttk.Checkbutton(actions, text='แจ้งในแอปและเสียง', variable=notifications, command=notification_toggle).pack(side='right', padx=12)
    footer = ttk.Frame(root, padding=(20, 8, 20, 8))
    footer.pack(fill='x')
    ttk.Label(footer, textvariable=status, style='Muted.TLabel', wraplength=1020).pack(anchor='w')
    context = ttk.Frame(root, padding=(20, 0, 20, 14))
    context.pack(fill='x')
    context_body = ttk.Frame(context)
    def toggle_context():
        if context_body.winfo_manager():
            context_body.pack_forget()
            context_button.configure(text='เปิดบันทึกส่งต่อบริบท')
        else:
            context_body.pack(fill='x', pady=(8, 0))
            context_button.configure(text='ย่อบันทึกส่งต่อบริบท')
    context_button = ttk.Button(context, text='เปิดบันทึกส่งต่อบริบท', command=toggle_context)
    context_button.pack(anchor='w')
    ttk.Label(context_body, text='บันทึกไว้แล้วคัดลอกไปวางในแชตใหม่ • ประวัติแชตจริงยังแยกตามผู้ให้บริการ', style='Muted.TLabel', wraplength=1000).pack(anchor='w')
    editor = tk.Text(context_body, height=4, wrap='word', font=('Leelawadee UI', 10), background='white', foreground=colors['ink'], relief='solid', borderwidth=1)
    editor.pack(fill='x')
    context_path = private_dir / 'context.md'
    try:
        if not smoke and not context_path.is_symlink() and context_path.exists() and context_path.stat().st_size <= 1024 * 1024:
            editor.insert('1.0', context_path.read_text(encoding='utf-8'))
    except OSError:
        status.set('Saved context could not be read')
    def save_context():
        from backend import _write
        try:
            if context_path.is_symlink():
                raise OSError()
            data = editor.get('1.0', 'end-1c').encode('utf-8')
            if len(data) > 1024 * 1024:
                raise ValueError('Context exceeds 1 MiB')
            context_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _write(context_path, data)
            status.set('Context saved locally. Copy and paste to hand off.')
        except Exception:
            messagebox.showerror('Context', 'Could not save context safely.', parent=root)
    def copy_context():
        root.clipboard_clear()
        root.clipboard_append(editor.get('1.0', 'end-1c'))
        status.set('Context copied to clipboard. Paste into your chosen chat.')
    context_actions = ttk.Frame(context_body)
    context_actions.pack(fill='x')
    ttk.Button(context_actions, text='บันทึกในเครื่อง', command=save_context).pack(side='left', pady=5)
    ttk.Button(context_actions, text='คัดลอกบริบท', command=copy_context).pack(side='left', padx=5)
    if smoke:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        state['accounts'] = [{'id': f'{p}:fixture{i}', 'provider': p, 'key': f'fixture{i}', 'label': f'บัญชีทดสอบ {i}', 'usageAccount': f'fixture{i}', 'email': None} for p in ('codex', 'claude') for i in range(25)]
        state['usage'] = {p: [{'provider': p, 'account': f'fixture{i}', 'usage': {'updatedAt': now.isoformat(), 'secondary': {'usedPercent': i, 'resetsAt': (now + timedelta(hours=2)).isoformat()}}} for i in range(25)] for p in ('codex', 'claude')}
        preferences['numbers'] = stable_numbers(state['accounts'], {})
        render()
        root.update_idletasks()
        assert len(panels['codex'].winfo_children()) == 25
        root.destroy()
        return
    root.after(100, poll)
    root.after(20000, sync_sessions)
    root.after(1000, refresh_timer)
    render()
    work(['list'])
    root.mainloop()

if __name__ == '__main__':
    main()
