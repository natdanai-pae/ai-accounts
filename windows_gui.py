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

def system_dpi(user32=None):
    if user32 is None:
        if os.name != 'nt':
            return 96
        import ctypes
        user32 = ctypes.windll.user32
    # Source previews need the same system awareness as the packaged manifest, before Tk creates HWNDs.
    user32.SetProcessDPIAware()
    if not user32.IsProcessDPIAware():
        raise RuntimeError('Windows could not enable system DPI awareness')
    dpi = user32.GetDpiForSystem()
    if not isinstance(dpi, int) or isinstance(dpi, bool) or dpi <= 0:
        raise RuntimeError('Windows returned an invalid system DPI')
    return dpi

def scaled_pixels(value, dpi):
    if isinstance(value, tuple):
        return tuple(scaled_pixels(part, dpi) for part in value)
    return int(value * dpi / 96 + 0.5)

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
    for name in ('secondary', 'primary') if usage.get('primary') is not None else ('secondary',):
        window = usage.get(name) or {}
        used, reset = window.get('usedPercent'), date(window.get('resetsAt'))
        if not number(used) or not 0 <= used < 100 or not reset or reset <= now:
            return None, 'Unknown, exhausted or expired quota'
        scores.append((100 - used) / max((reset - now).total_seconds() / 3600, 1 / 60))
    return scores[0], 'Weekly remaining quota before reset; prefer ready accounts first'

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
    ready = [(a, score) for a, score in eligible if ready_quota(values[a['id']])]
    return sorted(ready or eligible, key=lambda item: (-item[1], item[0]['id']))[0][0] if eligible else None

def ready_quota(usage):
    return 100 - usage['secondary']['usedPercent'] >= 10 and (usage.get('primary') is None or 100 - usage['primary']['usedPercent'] >= 20)

def quota_lanes(usage):
    return [('primary', 'รอบหลัก'), ('secondary', 'รายสัปดาห์')] if (usage or {}).get('primary') is not None else [('secondary', 'รายสัปดาห์')]

def recommendation_reason(accounts, values, winner, numbers, now=None):
    usage = values[winner['id']]
    suffix = ' • ประเมินจากรายสัปดาห์เท่านั้น' if usage.get('primary') is None else ''
    others = [a for a in accounts if a['provider'] == winner['provider'] and a['id'] != winner['id'] and values.get(a['id']) and recommendation(values[a['id']], now)[0] is not None]
    limited = next((a for a in others if not ready_quota(values[a['id']])), None)
    if ready_quota(usage) and limited:
        return f'มีโควตาพร้อมใช้กว่า บัญชี {numbers[limited["id"]]} ที่ใกล้หมด' + suffix
    if not ready_quota(usage):
        return 'ทุกบัญชีเหลือน้อย: บัญชีนี้ควรใช้ก่อนรอบสัปดาห์รีเซ็ต' + suffix
    if others:
        other = sorted(others, key=lambda a: numbers[a['id']])[0]
        return f'ควรใช้โควตาก่อนรีเซ็ตมากกว่าบัญชี {numbers[other["id"]]} ซึ่งเก็บไว้ใช้ต่อได้' + suffix
    return 'บัญชีนี้มีโควตาพร้อมใช้ และข้อมูลล่าสุดตรวจสอบได้' + suffix

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
            names = ('secondary', 'primary') if usage.get('primary') is not None else ('secondary',)
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

def reset_command(account, status, confirmed, busy):
    count = status.get('availableCount')
    if busy or not confirmed or account.get('provider') != 'codex' or status.get('ok') is not True or status.get('supported') is not True or status.get('eligible') is not True or not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return None
    if status.get('uncertain'):
        attempt = status.get('attemptId')
        if not isinstance(attempt, str) or not re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', attempt) or not isinstance(status.get('accountEmail'), str) or not status['accountEmail']:
            return None
    if account.get('email') and status.get('accountEmail') != account['email']:
        return None
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', account.get('key', '')):
        return None
    return ['reset', 'codex', account['key'], '--confirmed']

def reset_reason(status):
    if status.get('uncertain'):
        return 'คำขอเดิมยังไม่ทราบผล · ยังตรวจซ้ำไม่ได้'
    reason = str(status.get('reason') or '').lower()
    if '10%' in reason:
        return 'ใช้ได้เมื่อโควตารอบใดรอบหนึ่งเหลือไม่เกิน 10%'
    if 'no available' in reason or 'no verified unexpired' in reason:
        return 'ยังไม่มีสิทธิ์รีเซ็ตพร้อมใช้'
    if 'identity' in reason:
        return 'ตรวจสอบบัญชีไม่สำเร็จ'
    if not reason:
        return 'รอข้อมูลสิทธิ์รีเซ็ตล่าสุด'
    return 'ตรวจสิทธิ์ไม่ได้ · ดูรายละเอียด'

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

def preview_data(count=3, now=None):
    from datetime import timedelta
    now = now or datetime.now(timezone.utc)
    accounts = [{'id': f'{p}:fixture{i}', 'provider': p, 'key': f'fixture{i}', 'label': ('งานประจำ', 'งานโครงการ', 'บัญชีสำรอง')[i % 3], 'usageAccount': f'fixture{i}', 'email': None} for p in ('codex', 'claude') for i in range(count)]
    usage = {p: [{'provider': p, 'account': f'fixture{i}', 'usage': {'updatedAt': now.isoformat(), 'primary': {'usedPercent': (24, 61, 93)[i % 3], 'resetsAt': (now + timedelta(minutes=50+i*30)).isoformat()}, 'secondary': {'usedPercent': (38, 15, 72)[i % 3], 'resetsAt': (now + timedelta(hours=12+i*18)).isoformat()}}} for i in range(count)] for p in ('codex', 'claude')}
    resets = {a['id']: {'ok': True, 'supported': True, 'eligible': a['key'] == 'fixture2', 'availableCount': 2, 'expiresAt': (now+timedelta(days=3)).timestamp(), 'reason': 'Core five-hour or weekly remaining must be 10% or less'} for a in accounts if a['provider'] == 'codex'}
    return {'accounts': accounts, 'usage': usage, 'resetStatuses': resets}

def main():
    dpi = system_dpi()
    dp = lambda value: scaled_pixels(value, dpi)
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog
    root = tk.Tk()
    root.tk.call('tk', 'scaling', dpi / 72)
    root.title('AI Accounts • Windows beta')
    root.geometry(f'{dp(1120)}x{dp(850)}')
    root.minsize(dp(940), dp(680))
    colors = {'base': '#F3F6FA', 'card': '#FFFFFF', 'ink': '#213247', 'muted': '#627386', 'teal': '#087F8C', 'tint': '#E3F2F3', 'sidebar': '#203448'}
    root.configure(background=colors['base'])
    root.option_add('*Font', ('Leelawadee UI', 10))
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=('Leelawadee UI', 10), background=colors['base'], foreground=colors['ink'])
    style.configure('TButton', padding=dp((10, 5)), background='#EAF0F5', borderwidth=0)
    style.map('TButton', background=[('active', '#DDE8EF')])
    style.configure('Accent.TButton', foreground='white', background=colors['teal'])
    style.map('Accent.TButton', background=[('active', '#075A53')])
    style.configure('Card.TFrame', background=colors['card'])
    style.configure('Card.TLabel', background=colors['card'])
    style.configure('Muted.TLabel', foreground=colors['muted'])
    style.configure('CardMuted.TLabel', background=colors['card'], foreground=colors['muted'])
    style.configure('Ribbon.TFrame', background=colors['tint'])
    style.configure('Ribbon.TLabel', background=colors['tint'], foreground=colors['teal'])
    style.configure('Side.TFrame', background=colors['sidebar'])
    style.configure('Side.TLabel', background=colors['sidebar'], foreground='#E4ECF4')
    style.configure('Side.TButton', background='#2D465D', foreground='white', anchor='w', padding=dp((12, 9)), borderwidth=0)
    style.map('Side.TButton', background=[('active', '#395970')], foreground=[('active', 'white')])
    style.configure('Side.TCheckbutton', background=colors['sidebar'], foreground='#E4ECF4', padding=dp((0, 8)))
    style.map('Side.TCheckbutton', background=[('active', colors['sidebar'])], foreground=[('active', 'white')])
    style.configure('Quota.Horizontal.TProgressbar', background=colors['teal'], troughcolor='#E2EBEF', borderwidth=0, thickness=dp(5))
    smoke = '--self-test' in sys.argv
    preview = '--preview' in sys.argv or '--preview-empty' in sys.argv
    synthetic = smoke or preview
    if smoke:
        root.withdraw()
        # CI desktops may be smaller than the viewport under test.
        root.maxsize(dp(1120), dp(850))
        assert recommendation({'updatedAt': None})[0] is None
    resources = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    helper = resources / 'backend/aiaccounts-helper.exe'
    icon = resources / 'assets/AppIcon.png'
    if icon.exists():
        root._icon = tk.PhotoImage(file=str(icon))
        root.iconphoto(True, root._icon)
    events = queue.Queue()
    state = {'busy': False, 'accounts': [], 'usage': {}, 'resetStatuses': {}, 'lastRefresh': 0, 'lastPaint': 0}
    private_dir = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'AI Accounts'
    preferences_path = private_dir / 'ui-preferences.json'
    preferences = {'numbers': {}, 'alerts': {}, 'notifications': False}
    try:
        from backend import read_json
        if preferences_path.is_symlink():
            raise ValueError()
        loaded = {} if synthetic else read_json(preferences_path, {})
        if isinstance(loaded.get('numbers'), dict):
            preferences['numbers'] = loaded['numbers']
        if isinstance(loaded.get('alerts'), dict) and all(isinstance(loaded['alerts'].get(k, {}), dict) for k in ('winners', 'events', 'lastAlert')):
            preferences['alerts'] = loaded['alerts']
        preferences['notifications'] = loaded.get('notifications') is True
    except Exception:
        pass
    notifications = tk.BooleanVar(value=preferences['notifications'])
    sidebar = ttk.Frame(root, style='Side.TFrame', width=dp(180), padding=dp((14, 20)))
    sidebar.pack(side='left', fill='y')
    sidebar.pack_propagate(False)
    ttk.Label(sidebar, text='AI Accounts', style='Side.TLabel', font=('Segoe UI', 18, 'bold')).pack(anchor='w')
    ttk.Label(sidebar, text='บัญชีและโควตา AI', style='Side.TLabel', font=('Leelawadee UI', 9)).pack(anchor='w', pady=dp((3, 28)))
    main_area = ttk.Frame(root, padding=dp((20, 0, 16, 10)))
    main_area.pack(side='left', fill='both', expand=True)
    toolbar = ttk.Frame(main_area, padding=dp((0, 20, 0, 10)))
    toolbar.pack(fill='x')
    heading_copy = ttk.Frame(toolbar)
    heading_copy.pack(side='left', fill='x', expand=True)
    ttk.Label(heading_copy, text='บัญชีของคุณ' if not preview else 'ตัวอย่างหน้าจอ', font=('Leelawadee UI', 22, 'bold')).pack(anchor='w')
    status = tk.StringVar(value='กำลังอ่านข้อมูลบัญชีและโควตา…')
    status_label = ttk.Label(heading_copy, textvariable=status, style='Muted.TLabel', wraplength=dp(620), font=('Leelawadee UI', 9), cursor='hand2')
    status_label.pack(anchor='w', pady=dp((3, 0)), fill='x')
    status_label.bind('<Configure>', lambda e: e.widget.configure(wraplength=max(dp(180), e.width)))
    status_label.bind('<Button-1>', lambda e: messagebox.showinfo('สถานะล่าสุด', state.get('lastError') or status.get(), parent=root))
    ttk.Button(toolbar, text='รีเฟรช', command=lambda: work(['list'])).pack(side='right')
    actions = ttk.Frame(sidebar, style='Side.TFrame')
    actions.pack(fill='x')
    notice = tk.StringVar(value='ตัวอย่างข้อมูลจำลอง • ไม่เชื่อมบัญชีจริงและไม่บันทึกการตั้งค่า' if preview else 'เลือกบัญชีได้เองทุกครั้ง • รีเฟรชโควตาอัตโนมัติทุก 5 นาที')
    ttk.Label(main_area, textvariable=notice, foreground=colors['teal'], wraplength=dp(850), padding=dp((0, 2, 0, 14)), font=('Leelawadee UI', 9)).pack(fill='x')
    columns = ttk.Frame(main_area)
    columns.pack(fill='both', expand=True)
    panels, ribbons, scroll_surfaces = {}, {}, []
    for provider in ('codex', 'claude'):
        column = 0 if provider == 'codex' else 1
        columns.columnconfigure(column, weight=1, uniform='providers')
        columns.rowconfigure(0, weight=1)
        pane = ttk.Frame(columns, padding=dp((0, 0, 8 if column == 0 else 0, 0)))
        pane.grid(row=0, column=column, sticky='nsew')
        heading = ttk.Frame(pane)
        heading.pack(fill='x', pady=dp((0, 10)))
        ttk.Label(heading, text=provider.title(), font=('Segoe UI', 18, 'bold')).pack(side='left')
        ttk.Button(heading, text='+ เพิ่มบัญชี', command=lambda p=provider: add(p)).pack(side='right')
        ribbon = ttk.Frame(pane, style='Ribbon.TFrame', padding=dp((10, 7)))
        ribbon.pack(fill='x', pady=dp((0, 6)))
        ribbons[provider] = ribbon
        canvas = tk.Canvas(pane, highlightthickness=0, width=dp(350), background=colors['base'])
        scroll = ttk.Scrollbar(pane, orient='vertical', command=canvas.yview)
        def update_scroll(first, last, bar=scroll, surface=canvas):
            bar.set(first, last)
            if float(first) <= 0 and float(last) >= 1:
                bar.pack_forget()
            elif not bar.winfo_manager():
                bar.pack(side='right', fill='y', before=surface)
        canvas.configure(yscrollcommand=update_scroll)
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
        if synthetic:
            raise RuntimeError('โหมดตัวอย่างไม่เรียกผู้ให้บริการ')
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
        if synthetic:
            status.set('ข้อมูลจำลองเท่านั้น • ไม่มีการเรียกผู้ให้บริการ')
            return
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
                from concurrent.futures import ThreadPoolExecutor
                def reset_status(account):
                    try:
                        return account['id'], invoke(['reset-status', 'codex', account['key']])
                    except Exception:
                        return account['id'], {'supported': False, 'reason': 'อ่านสิทธิ์รีเซ็ตไม่สำเร็จ'}
                with ThreadPoolExecutor(max_workers=2) as pool:
                    usage['_resetStatuses'] = dict(pool.map(reset_status, [a for a in accounts if a['provider'] == 'codex']))
                events.put((accounts, usage, {'text': 'อัปเดตล่าสุด ' + datetime.now().strftime('%H:%M') + ' • ' + str(len(accounts)) + ' บัญชี', 'details': result.get('message', '') if isinstance(result, dict) else ''}))
            except RuntimeError as error:
                events.put((None, None, {'text': 'ยังยืนยันผลรีเซ็ตไม่ได้ • คลิกเพื่อดูรายละเอียด' if args[0] == 'reset' else 'ทำรายการไม่สำเร็จ • คลิกเพื่อดูรายละเอียด', 'details': str(error)}))
            except Exception:
                events.put((None, None, 'ตรวจการเข้าสู่ระบบและแอปผู้ให้บริการ แล้วลองอีกครั้ง'))
        threading.Thread(target=run, daemon=True).start()

    def switch(account):
        if synthetic:
            messagebox.showinfo('ตัวอย่าง', 'ตัวอย่างปุ่มสลับบัญชี • ไม่มีการสลับบัญชีจริง', parent=root)
            return
        if state['busy']:
            return
        if messagebox.askokcancel('สลับบัญชี', 'บันทึกงานก่อนสลับ และปิดหน้าต่าง Codex เองก่อนสลับ Codex\n\nสลับไป ' + account_title(account) + '?', parent=root):
            work(['switch', account['provider'], account['key']])

    def add(provider):
        if synthetic:
            messagebox.showinfo('ตัวอย่าง', 'เมื่อใช้งานจริง ปุ่มนี้จะเปิดขั้นตอนเข้าสู่ระบบของ ' + provider.title(), parent=root)
            return
        if state['busy']:
            return
        label = simpledialog.askstring('เพิ่มบัญชี ' + provider.title(), 'ชื่อบัญชี (ขั้นต่อไปจะเปิดหน้าต่างเข้าสู่ระบบตามปกติ):', parent=root)
        if label:
            work(['add', provider, label])

    def request_reset(account):
        if synthetic:
            messagebox.showinfo('ตัวอย่าง', 'ตัวอย่างปุ่มรีเซ็ต • ไม่มีการใช้สิทธิ์หรือเรียกผู้ให้บริการ', parent=root)
            return
        if state['busy']:
            return
        state['busy'] = True
        status.set('กำลังตรวจสิทธิ์รีเซ็ตล่าสุด • ยังไม่ใช้สิทธิ์')
        def check():
            try:
                data = invoke(['reset-status', account['provider'], account['key']])
            except Exception:
                data = {'supported': False, 'reason': 'อ่านสิทธิ์รีเซ็ตไม่สำเร็จ กรุณารีเฟรช'}
            events.put(('reset-status', account, data))
        threading.Thread(target=check, daemon=True).start()

    def save_preferences():
        if synthetic:
            return
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
        reset_status = state['resetStatuses'].get(account['id'], {})
        if reset_status.get('reason'):
            lines.append('สถานะสิทธิ์รีเซ็ต: ' + str(reset_status['reason']))
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
        lines.append('เลือกบัญชีที่รอบหลักเหลืออย่างน้อย 20% และรายสัปดาห์อย่างน้อย 10% ก่อนเมื่อมีตัวเลือก จากนั้นเลือกโควตารายสัปดาห์ที่ควรใช้ก่อนรีเซ็ต ไม่เปรียบเทียบข้ามผู้ให้บริการ ไม่ใช่จำนวนโทเคน และไม่สลับบัญชีอัตโนมัติ')
        messagebox.showinfo('รายละเอียดบัญชี', '\n\n'.join(lines), parent=root)

    def render():
        state['lastPaint'] = time.time()
        values = values_by_account()
        populated = {p: any(a['provider'] == p for a in state['accounts']) for p in ('codex', 'claude')}
        for index, provider in enumerate(('codex', 'claude')):
            only_one = sum(populated.values()) == 1
            columns.columnconfigure(index, uniform='' if only_one else 'providers', weight=(1 if populated[provider] else 0) if only_one else 1, minsize=dp(220 if only_one and not populated[provider] else 0))
        for provider, panel in panels.items():
            for widget in panel.winfo_children():
                widget.destroy()
            accounts = ordered_accounts([a for a in state['accounts'] if a['provider'] == provider], preferences['numbers'])
            winner = provider_winner(accounts, values, provider)
            ribbon = ribbons[provider]
            canvas = scroll_surfaces[0 if provider == 'codex' else 1][1]
            canvas.pack_configure(expand=bool(accounts), fill='both' if accounts else 'x')
            canvas.configure(height=dp(240 if not accounts else 400), width=dp(200 if not accounts else 350))
            if accounts:
                ribbon.pack(fill='x', pady=dp((0, 10)), before=canvas)
            else:
                ribbon.pack_forget()
            for widget in ribbon.winfo_children():
                widget.destroy()
            if winner:
                usage = values[winner['id']]
                week = usage['secondary']
                heading = ttk.Frame(ribbon, style='Ribbon.TFrame')
                heading.pack(fill='x')
                ttk.Label(heading, text='แนะนำบัญชี ' + str(preferences['numbers'][winner['id']]), style='Ribbon.TLabel', font=('Leelawadee UI', 11, 'bold')).pack(side='left')
                ttk.Label(heading, text=f'เหลือ {100-week["usedPercent"]:g}%', style='Ribbon.TLabel').pack(side='right')
                reason_label = ttk.Label(ribbon, text=recommendation_reason(accounts, values, winner, preferences['numbers']), style='Ribbon.TLabel', wraplength=dp(370), font=('Leelawadee UI', 9))
                reason_label.pack(anchor='w', pady=dp((3, 0)), fill='x')
                reason_label.bind('<Configure>', lambda e: e.widget.configure(wraplength=max(dp(160), e.width)))
            else:
                ttk.Label(ribbon, text='ยังไม่มีบัญชีที่แนะนำ', style='Ribbon.TLabel', font=('Leelawadee UI', 11, 'bold')).pack(anchor='w')
                unavailable = ttk.Label(ribbon, text='รีเฟรชโควตาและเวลารีเซ็ต • ข้อมูลต้องไม่เกิน 15 นาที', style='Ribbon.TLabel', wraplength=dp(360))
                unavailable.pack(anchor='w', pady=dp(3), fill='x')
                unavailable.bind('<Configure>', lambda e: e.widget.configure(wraplength=max(dp(160), e.width)))
            if not accounts:
                empty = ttk.Frame(panel, style='Card.TFrame', padding=dp((16, 20)))
                empty.pack(fill='x')
                ttk.Label(empty, text='เริ่มใช้ ' + provider.title(), style='Card.TLabel', font=('Leelawadee UI', 14, 'bold')).pack(anchor='w')
                instruction = ttk.Label(empty, text='เพิ่มบัญชีแล้วเข้าสู่ระบบ\nจากนั้นเชื่อมโควตาจากแถบด้านซ้าย', style='CardMuted.TLabel', wraplength=dp(190))
                instruction.pack(anchor='w', pady=dp((8, 16)), fill='x')
                instruction.bind('<Configure>', lambda e: e.widget.configure(wraplength=max(dp(140), e.width)))
                ttk.Button(empty, text='+ เพิ่มบัญชีแรก', style='Accent.TButton', command=lambda p=provider: add(p)).pack(anchor='w')
            for account in accounts:
                usage = values.get(account['id'])
                row = ttk.Frame(panel, padding=dp((12, 7)), style='Card.TFrame')
                row.pack(fill='x', pady=dp((0, 8)))
                top = ttk.Frame(row, style='Card.TFrame')
                top.pack(fill='x')
                label = str(account.get('label') or account['key'])
                label = label[:18] + '…' if len(label) > 19 else label
                tk.Label(top, text=str(preferences['numbers'][account['id']]), font=('Segoe UI', 22, 'bold'), background=colors['tint'], foreground=colors['teal'], width=2).pack(side='left', padx=dp((0, 10)))
                identity = ttk.Frame(top, style='Card.TFrame')
                identity.pack(side='left', fill='x', expand=True)
                ttk.Label(identity, text=label, style='Card.TLabel', font=('Leelawadee UI', 11, 'bold')).pack(anchor='w')
                ttk.Label(identity, text='แนะนำให้ใช้ตอนนี้' if winner and winner['id'] == account['id'] else 'บัญชี ' + str(preferences['numbers'][account['id']]), style='CardMuted.TLabel', font=('Leelawadee UI', 9)).pack(anchor='w')
                ttk.Button(top, text='ใช้บัญชีนี้', style='Accent.TButton', command=lambda a=account: switch(a)).pack(side='right')
                lanes = ttk.Frame(row, style='Card.TFrame')
                lanes.pack(fill='x', pady=dp((6, 2)))
                lane_items = quota_lanes(usage)
                for index, (key, label) in enumerate(lane_items):
                    cell = ttk.Frame(lanes, style='Card.TFrame')
                    cell.pack(fill='x', pady=dp(2))
                    window = (usage or {}).get(key) or {}
                    used = window.get('usedPercent')
                    valid = number(used) and 0 <= used <= 100
                    ttk.Label(cell, text=label, style='CardMuted.TLabel', width=7, font=('Leelawadee UI', 9)).pack(side='left')
                    ttk.Label(cell, text=f'{100-used:g}%' if valid else '—', style='Card.TLabel', width=4, font=('Segoe UI', 11, 'bold')).pack(side='left')
                    ttk.Progressbar(cell, style='Quota.Horizontal.TProgressbar', maximum=100, value=100-used if valid else 0, length=dp(40)).pack(side='left', fill='x', expand=True, padx=dp((0, 8)))
                    reset = date(window.get('resetsAt'))
                    reset_label = reset.astimezone().strftime('%d/%m %H:%M') if reset else 'ไม่ทราบ'
                    ttk.Label(cell, text='รีเซ็ต ' + reset_label, style='CardMuted.TLabel', font=('Leelawadee UI', 9)).pack(side='right')
                if len(lane_items) == 1:
                    ttk.Label(row, text='รอบสั้นไม่มีข้อมูล', style='CardMuted.TLabel', font=('Leelawadee UI', 9)).pack(anchor='w')
                if not usage or recommendation(usage)[0] is None:
                    ttk.Label(row, text='ไม่ใช้แนะนำ: โควตาหมด ข้อมูลเก่า หรือข้อมูลไม่ครบ', style='CardMuted.TLabel', font=('Leelawadee UI', 9)).pack(anchor='w')
                source = next((r for r in state['usage'].get(provider, []) if isinstance(r, dict) and r.get('usage') is usage), {}) if usage else {}
                reset_info = state['resetStatuses'].get(account['id'], {})
                count = reset_info.get('availableCount', (source.get('resetCredits') or {}).get('available'))
                reset_line = ttk.Frame(row, style='Card.TFrame')
                reset_line.pack(fill='x', pady=dp((5, 0)))
                stamp = reset_info.get('expiresAt')
                try:
                    expiry = datetime.fromtimestamp(stamp, timezone.utc) if number(stamp) else None
                except (ValueError, OverflowError, OSError):
                    expiry = None
                expiry_text = expiry.astimezone().strftime('%d/%m %H:%M') if expiry else 'ไม่ทราบ'
                ttk.Label(reset_line, text='รีเซ็ตฟรี ' + (str(count) + ' ครั้ง' if number(count) else 'ไม่ทราบ') + '\nหมดอายุ ' + expiry_text, style='CardMuted.TLabel', font=('Leelawadee UI', 9)).pack(side='left')
                enabled = reset_command(account, reset_info, True, False) is not None
                ttk.Button(reset_line, text='ดูข้อมูล', command=lambda a=account, u=usage: details(a, u)).pack(side='right')
                ttk.Button(reset_line, text='ตรวจคำขอเดิม' if reset_info.get('uncertain') else 'รีเซ็ตฟรี', command=lambda a=account: request_reset(a), state='normal' if enabled else 'disabled').pack(side='right', padx=dp(5))
                if not enabled:
                    reason = 'Claude ยังไม่รองรับรีเซ็ตจากแอปนี้' if provider == 'claude' else reset_reason(reset_info)
                    reason_label = ttk.Label(row, text=reason, style='CardMuted.TLabel', font=('Leelawadee UI', 9), wraplength=dp(360))
                    reason_label.pack(anchor='w', fill='x')
                    reason_label.bind('<Configure>', lambda e: e.widget.configure(wraplength=max(dp(160), e.width)))

    def poll():
        try:
            accounts, usage, message = events.get_nowait()
            if accounts == 'reset-status':
                account, reset_status = usage, message
                state['resetStatuses'][account['id']] = reset_status
                command = reset_command(account, reset_status, True, False)
                confirmed = False
                if command:
                    if reset_status.get('uncertain'):
                        title = 'ยืนยันตรวจคำขอเดิม'
                        explanation = '\n\nคำขอก่อนหน้ายังไม่ทราบผล จะใช้รหัสเดิมนี้เท่านั้น:\n' + reset_status['attemptId'] + '\nไม่สร้างคำขอใช้สิทธิ์ใหม่ ระบบอาจทำคำขอเดิมให้เสร็จ\nสิทธิ์ฟรี 1 ครั้งยังผูกกับคำขอเดิม\n\nต้องการตรวจคำขอเดิมหรือไม่?'
                    else:
                        title = 'ยืนยันใช้สิทธิ์รีเซ็ตฟรี'
                        explanation = '\n\nการดำเนินการนี้ใช้สิทธิ์ฟรี 1 ครั้งเพื่อรีเซ็ตโควตา\nไม่ซื้อเครดิต ไม่เปลี่ยนแพ็กเกจ และไม่สลับบัญชี\n\nต้องการใช้สิทธิ์ตอนนี้หรือไม่?'
                    confirmed = messagebox.askokcancel(title, account_title(account) + '\n' + str(reset_status.get('accountEmail') or 'ตรวจสอบบัญชีแล้ว') + explanation, parent=root)
                else:
                    messagebox.showinfo('ยังรีเซ็ตไม่ได้', reset_reason(reset_status), parent=root)
                state['busy'] = False
                render()
                if confirmed:
                    work(command)
                else:
                    status.set('ไม่ได้ส่งคำขอเพิ่มเติม')
                root.after(100, poll)
                return
            state['busy'] = False
            if accounts is not None:
                state.update(accounts=accounts, usage=usage, resetStatuses=usage.pop('_resetStatuses', {}))
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
            if isinstance(message, dict):
                state['lastError'] = message['details']
                status.set(message['text'])
            else:
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
                    events.put((None, None, 'แชร์เซสชันยังไม่พร้อม • เปิด Code ในแต่ละบัญชีแล้วตั้งค่าอีกครั้ง'))
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

    for title, command in [('เชื่อมข้อมูลโควตา', 'connect'), ('แชร์เซสชัน', 'setup')]:
        ttk.Button(actions, text=title, style='Side.TButton', command=lambda c=command: work([c])).pack(fill='x', pady=dp((0, 7)))
    context = tk.Toplevel(root)
    context.withdraw()
    context.title('บันทึกส่งต่อบริบท')
    context.geometry(f'{dp(620)}x{dp(330)}')
    context.configure(background=colors['base'])
    context.protocol('WM_DELETE_WINDOW', context.withdraw)
    context_body = ttk.Frame(context, padding=dp(16))
    context_body.pack(fill='both', expand=True)
    def toggle_context():
        context.deiconify()
        context.lift()
    ttk.Button(actions, text='บันทึกส่งต่อบริบท', style='Side.TButton', command=toggle_context).pack(fill='x', pady=dp((0, 24)))
    ttk.Label(sidebar, text='การแจ้งเตือน', style='Side.TLabel', font=('Leelawadee UI', 10, 'bold')).pack(anchor='w')
    ttk.Checkbutton(sidebar, text='ข้อความและเสียง', style='Side.TCheckbutton', variable=notifications, command=notification_toggle).pack(anchor='w')
    ttk.Button(sidebar, text='ตั้งค่าการแจ้งเตือน', style='Side.TButton', command=notification_help).pack(fill='x')
    ttk.Label(sidebar, text='ข้อมูลอยู่ในเครื่อง\nไม่สลับบัญชีอัตโนมัติ', style='Side.TLabel', font=('Leelawadee UI', 9)).pack(side='bottom', anchor='w', pady=dp(4))
    ttk.Label(context_body, text='บันทึกไว้แล้วคัดลอกไปวางในแชตใหม่ • ประวัติแชตจริงยังแยกตามผู้ให้บริการ', style='Muted.TLabel', wraplength=dp(570)).pack(anchor='w')
    editor = tk.Text(context_body, height=4, wrap='word', font=('Leelawadee UI', 10), background='white', foreground=colors['ink'], relief='solid', borderwidth=1)
    editor.pack(fill='x')
    context_path = private_dir / 'context.md'
    try:
        if not synthetic and not context_path.is_symlink() and context_path.exists() and context_path.stat().st_size <= 1024 * 1024:
            editor.insert('1.0', context_path.read_text(encoding='utf-8'))
    except OSError:
        status.set('อ่านบันทึกบริบทไม่ได้ • ตรวจสอบไฟล์ในเครื่อง')
    def save_context():
        if synthetic:
            messagebox.showinfo('ตัวอย่าง', 'โหมดตัวอย่างไม่บันทึกไฟล์', parent=context)
            return
        from backend import _write
        try:
            if context_path.is_symlink():
                raise OSError()
            data = editor.get('1.0', 'end-1c').encode('utf-8')
            if len(data) > 1024 * 1024:
                raise ValueError('Context exceeds 1 MiB')
            context_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _write(context_path, data)
            status.set('บันทึกบริบทในเครื่องแล้ว • คัดลอกไปวางในแชตที่เลือก')
        except Exception:
            messagebox.showerror('บันทึกบริบท', 'บันทึกไฟล์ไม่ได้ กรุณาตรวจสอบพื้นที่และสิทธิ์ของไฟล์', parent=context)
    def copy_context():
        root.clipboard_clear()
        root.clipboard_append(editor.get('1.0', 'end-1c'))
        status.set('คัดลอกบริบทแล้ว • วางลงในแชตที่เลือก')
    context_actions = ttk.Frame(context_body)
    context_actions.pack(fill='x')
    ttk.Button(context_actions, text='บันทึกในเครื่อง', command=save_context).pack(side='left', pady=dp(5))
    ttk.Button(context_actions, text='คัดลอกบริบท', command=copy_context).pack(side='left', padx=dp(5))
    def show_preview(count, one_provider=False):
        state.update(preview_data(count))
        if one_provider:
            state['accounts'] = [a for a in state['accounts'] if a['provider'] == 'codex']
        preferences['numbers'] = stable_numbers(state['accounts'], {})
        status.set('ข้อมูลจำลอง • ไม่มีการเชื่อมต่อบัญชีจริง')
        render()
    if preview:
        ttk.Label(sidebar, text='ตัวอย่างหน้าจอ', style='Side.TLabel', font=('Leelawadee UI', 10, 'bold')).pack(anchor='w', pady=dp((24, 6)))
        for title, count, one in [('6 บัญชี', 3, False), ('1 บัญชี / ยังไม่มี Claude', 1, True), ('ยังไม่มีบัญชี', 0, False), ('50 บัญชี', 25, False)]:
            ttk.Button(sidebar, text=title, style='Side.TButton', command=lambda n=count, o=one: show_preview(n, o)).pack(fill='x', pady=dp(3))
        show_preview(0 if '--preview-empty' in sys.argv else 3)
        root.mainloop()
        return
    if smoke:
        show_preview(25)
        root.update_idletasks()
        assert len(panels['codex'].winfo_children()) == 25
        show_preview(3)
        root.deiconify()
        root.update_idletasks()
        for provider, (_, canvas) in zip(('codex', 'claude'), scroll_surfaces):
            rows = panels[provider].winfo_children()
            assert len(rows) == 3
            assert rows[-1].winfo_y() + rows[-1].winfo_height() <= canvas.winfo_height(), f'Three accounts must fit: provider={provider}, root={root.winfo_geometry()}, rowsBottom={rows[-1].winfo_y() + rows[-1].winfo_height()}, canvas={canvas.winfo_height()}, scaling={root.tk.call("tk", "scaling")}'
        root.destroy()
        return
    root.after(100, poll)
    root.after(20000, sync_sessions)
    root.after(1000, refresh_timer)
    render()
    work(['list'])
    root.mainloop()

if __name__ == '__main__':
    if '--self-test' in sys.argv:
        try:
            main()
        except Exception:
            import traceback
            Path(sys.executable if getattr(sys, 'frozen', False) else __file__).with_name('ai-accounts-selftest-error.log').write_text(traceback.format_exc(), encoding='utf-8')
            sys.exit(1)
    else:
        main()
