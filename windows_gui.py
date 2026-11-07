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
        if not isinstance(row, dict) or row.get('provider') != account['provider'] or not isinstance(row.get('usage'), dict):
            continue
        usage = row['usage']
        matches_id = usage.get('accountEmail') == account['email'] if account.get('email') else bool(account.get('usageAccount')) and row.get('account') == account['usageAccount']
        if matches_id:
            matches.append(usage)
    return max(matches, key=lambda u: date(u.get('updatedAt')) or datetime.min.replace(tzinfo=timezone.utc)) if matches else None

def main():
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog
    root = tk.Tk()
    root.title('AI Accounts • Windows beta')
    root.geometry('1100x780')
    root.minsize(850, 600)
    if '--self-test' in sys.argv:
        root.withdraw()
        assert recommendation({'updatedAt': None})[0] is None
        root.update_idletasks()
        root.destroy()
        return
    resources = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    helper = resources / 'backend/aiaccounts-helper.exe'
    icon = resources / 'assets/AppIcon.png'
    if icon.exists():
        root._icon = tk.PhotoImage(file=str(icon))
        root.iconphoto(True, root._icon)
    events = queue.Queue()
    state = {'busy': False, 'accounts': [], 'usage': {}}
    toolbar = ttk.Frame(root, padding=14)
    toolbar.pack(fill='x')
    ttk.Label(toolbar, text='AI Accounts', font=('Segoe UI', 22, 'bold')).pack(side='left')
    status = tk.StringVar(value='Loading accounts…')
    ttk.Label(root, textvariable=status, wraplength=1050, padding=(14, 0, 14, 10)).pack(fill='x')
    columns = ttk.Frame(root, padding=10)
    columns.pack(fill='both', expand=True)
    panels = {}
    for provider in ('codex', 'claude'):
        pane = ttk.LabelFrame(columns, text=provider.title(), padding=8)
        pane.pack(side='left', fill='both', expand=True, padx=4)
        canvas = tk.Canvas(pane, highlightthickness=0, width=450)
        scroll = ttk.Scrollbar(pane, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        rows = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=rows, anchor='nw')
        rows.bind('<Configure>', lambda e, c=canvas: c.configure(scrollregion=c.bbox('all')))
        canvas.bind('<Configure>', lambda e, c=canvas, w=window: c.itemconfigure(w, width=e.width))
        canvas.bind('<MouseWheel>', lambda e, c=canvas: c.yview_scroll(-int(e.delta / 120), 'units'))
        panels[provider] = rows

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
        status.set('Working… Complete provider login if a window opens. Do not close this app.')
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
        if messagebox.askokcancel('Switch account', 'Save active work first. Close the running Codex app manually before switching Codex.\n\nSwitch to ' + str(account.get('label', account['key'])) + '?', parent=root):
            work(['switch', account['provider'], account['key']])

    def add(provider):
        if state['busy']:
            return
        label = simpledialog.askstring('Add ' + provider.title(), 'Account label (normal provider login opens next):', parent=root)
        if label:
            work(['add', provider, label])

    def render():
        for provider, panel in panels.items():
            for widget in panel.winfo_children():
                widget.destroy()
            ttk.Button(panel, text='+ Add account', command=lambda p=provider: add(p)).pack(anchor='w', pady=4)
            accounts = [a for a in state['accounts'] if a['provider'] == provider]
            ranked = [(a, match_usage(a, state['usage'].get(provider, []))) for a in accounts]
            scores = {a['id']: recommendation(u)[0] for a, u in ranked if u}
            eligible = [a for a in accounts if scores.get(a['id']) is not None]
            winner = sorted(eligible, key=lambda a: (-scores[a['id']], a['id']))[0]['id'] if eligible else None
            if not accounts:
                ttk.Label(panel, text='Add an account, complete login, then Connect and Setup.', wraplength=400).pack(pady=20)
            for account, usage in ranked:
                row = ttk.Frame(panel, padding=(5, 12))
                row.pack(fill='x')
                title = str(account.get('label', account['key'])) + ('  ★ Recommended' if account['id'] == winner else '')
                ttk.Label(row, text=title, font=('Segoe UI', 12, 'bold'), wraplength=400).pack(anchor='w')
                ttk.Label(row, text=account.get('email') or 'Identity not connected', wraplength=400).pack(anchor='w')
                detail = 'Quota unavailable — Connect / Refresh'
                if usage:
                    lines = []
                    for key, label in (('secondary', 'Weekly'), ('primary', 'Primary')):
                        if key in usage:
                            value = usage[key] or {}
                            used = value.get('usedPercent')
                            left = f'{100-used:g}%' if number(used) and 0 <= used <= 100 else 'unknown'
                            lines.append(f'{label}: {left} remaining · resets {value.get("resetsAt") or "unknown"}')
                    lines.append('Updated: ' + str(usage.get('updatedAt') or 'unknown'))
                    source_row = next((r for r in state['usage'].get(provider, []) if isinstance(r, dict) and r.get('usage') is usage), {})
                    credits = source_row.get('credits') or {}
                    resets = source_row.get('resetCredits') or {}
                    balance = credits.get('remaining') if provider == 'codex' else (usage.get('providerCost') or {}).get('balance')
                    currency = (' ' + str((usage.get('providerCost') or {}).get('currencyCode', ''))) if provider == 'claude' else ''
                    lines.append('Credits: ' + (str(balance) + currency if number(balance) else 'unknown') + ' · reset credits: ' + (str(resets['available']) if number(resets.get('available')) else 'unknown'))
                    lines.append(recommendation(usage)[1])
                    detail = '\n'.join(lines)
                ttk.Label(row, text=detail, wraplength=400).pack(anchor='w', pady=6)
                ttk.Button(row, text='Switch to this account', command=lambda a=account: switch(a)).pack(anchor='w')

    def poll():
        try:
            accounts, usage, message = events.get_nowait()
            state['busy'] = False
            if accounts is not None:
                state.update(accounts=accounts, usage=usage)
                render()
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
                    events.put((None, None, 'Session sync checked'))
                except Exception:
                    events.put((None, None, 'Session sync unavailable; open Code for each account and run Setup.'))
            threading.Thread(target=run_sync, daemon=True).start()
        root.after(20000, sync_sessions)

    for title, command in [('Refresh', 'list'), ('Connect quotas', 'connect'), ('Setup shared sessions', 'setup')]:
        ttk.Button(toolbar, text=title, command=lambda c=command: work([c])).pack(side='left', padx=5)
    context = ttk.LabelFrame(root, text='Shared context handoff • paste into a new provider chat; native history stays with its provider', padding=8)
    context.pack(fill='x', padx=14, pady=10)
    editor = tk.Text(context, height=5, wrap='word', font=('Segoe UI', 10))
    editor.pack(fill='x')
    context_path = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'AI Accounts/context.md'
    try:
        if not context_path.is_symlink() and context_path.exists() and context_path.stat().st_size <= 1024 * 1024:
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
    ttk.Button(context, text='Save locally', command=save_context).pack(side='left', pady=5)
    ttk.Button(context, text='Copy context', command=copy_context).pack(side='left', padx=5)
    root.after(100, poll)
    root.after(20000, sync_sessions)
    work(['list'])
    root.mainloop()

if __name__ == '__main__':
    main()
