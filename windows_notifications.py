"""Opt-in native Windows desktop toasts, using only Windows and Python stdlib.

Call register_notifications on explicit opt-in, then send_notification from a
worker thread. `accepted` means Show returned, NOT that a banner was observed;
Windows focus/notification settings still control presentation. No click actions.

Microsoft contracts:
https://learn.microsoft.com/windows/win32/shell/enable-desktop-toast-with-appusermodelid
https://learn.microsoft.com/windows/win32/shell/quickstart-sending-desktop-toast
https://learn.microsoft.com/windows/win32/api/shobjidl_core/nf-shobjidl_core-shgetpropertystorefromparsingname
"""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

APP_ID = 'AIAccounts.Desktop'
_MESSAGES = {
    'registered': 'ลงทะเบียนการแจ้งเตือน AI Accounts แล้ว',
    'accepted': 'ส่งคำขอแจ้งเตือนให้ Windows แล้ว โปรดตรวจแบนเนอร์หรือศูนย์การแจ้งเตือน',
    'disabled': 'Windows ปิดการแจ้งเตือนนี้อยู่ โปรดตรวจการตั้งค่าการแจ้งเตือน',
    'registration_required': 'โปรดเปิดการแจ้งเตือนเพื่อลงทะเบียน AI Accounts ก่อน',
    'unsupported': 'การแจ้งเตือนนี้รองรับเฉพาะ Windows',
    'invalid': 'ข้อมูลการแจ้งเตือนหรือที่อยู่แอปไม่ถูกต้อง',
    'timeout': 'Windows ตอบกลับช้าเกินไป โปรดลองทดสอบอีกครั้ง',
    'failed': 'ส่งการแจ้งเตือนไม่สำเร็จ โปรดลองทดสอบอีกครั้ง',
}

# Fixed code; all caller-controlled values arrive as base64 JSON data. No policy,
# execution-policy bypass, registry changes, elevation, network, or shell=True.
# First-use bootstrap follows Microsoft Toolkit ToastNotifierCompat.Setting.
_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$stage = 'registration'
try {
  $programs = [Environment]::GetFolderPath('Programs')
  $shortcut = Join-Path $programs 'AI Accounts.lnk'
  if ($data.operation -eq 'register') {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[StructLayout(LayoutKind.Sequential)] public struct PropertyKey {
  public Guid fmtid; public uint pid;
}
[StructLayout(LayoutKind.Explicit, Size=24)] public struct PropertyValue {
  [FieldOffset(0)] public ushort vt;
  [FieldOffset(8)] public IntPtr value;
}
[ComImport, Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IPropertyStore {
  void GetCount(out uint count);
  void GetAt(uint index, out PropertyKey key);
  void GetValue(ref PropertyKey key, out PropertyValue value);
  void SetValue(ref PropertyKey key, ref PropertyValue value);
  void Commit();
}
public static class ShortcutIdentity {
  [DllImport("shell32.dll", CharSet=CharSet.Unicode, PreserveSig=false)]
  static extern void SHGetPropertyStoreFromParsingName(string path, IntPtr context,
    uint flags, ref Guid iid, [MarshalAs(UnmanagedType.Interface)] out IPropertyStore store);
  public static void Set(string path, string appId) {
    var iid = typeof(IPropertyStore).GUID;
    IPropertyStore store;
    SHGetPropertyStoreFromParsingName(path, IntPtr.Zero, 2, ref iid, out store);
    var key = new PropertyKey { fmtid = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3"), pid = 5 };
    var value = new PropertyValue { vt = 31, value = Marshal.StringToCoTaskMemUni(appId) };
    try { store.SetValue(ref key, ref value); store.Commit(); }
    finally { Marshal.FreeCoTaskMem(value.value); Marshal.ReleaseComObject(store); }
  }
}
'@
    $link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
    $link.TargetPath = $data.executable
    $link.Arguments = $data.arguments
    $link.WorkingDirectory = [IO.Path]::GetDirectoryName($data.executable)
    $link.Description = 'AI Accounts'
    $link.IconLocation = $data.icon
    $backup = Join-Path $programs 'AI Accounts.before-notifications.lnk'
    if ([IO.File]::Exists($shortcut) -and ![IO.File]::Exists($backup)) {
      [IO.File]::Copy($shortcut, $backup, $false)
    }
    $link.Save()
    [ShortcutIdentity]::Set($shortcut, $data.appId)
  }
  if (!(Test-Path -LiteralPath $shortcut)) { @{status='registration_required'} | ConvertTo-Json -Compress; exit }
  $folder = (New-Object -ComObject Shell.Application).NameSpace($programs)
  $item = $folder.ParseName('AI Accounts.lnk')
  if ($item.ExtendedProperty('System.AppUserModel.ID') -ne $data.appId) {
    @{status='registration_required'} | ConvertTo-Json -Compress; exit
  }
  [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null
  [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] > $null
  $stage = 'notifier'
  $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($data.appId)
  if ($data.operation -eq 'register') {
    # Win32 senders must submit once before Setting can be queried (Microsoft Toolkit).
    $stage = 'bootstrap'
    $initialXml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $initialXml.LoadXml('<toast><visual><binding template="ToastGeneric"><text>AI Accounts registration</text></binding></visual></toast>')
    $initial = [Windows.UI.Notifications.ToastNotification]::new($initialXml)
    $initial.SuppressPopup = $true
    $initial.Tag = 'AIAccountsInit'
    $initial.Group = 'registration'
    $initial.ExpirationTime = [DateTimeOffset]::Now.AddSeconds(15)
    $notifier.Show($initial)
    [Windows.UI.Notifications.ToastNotificationManager]::History.Remove('AIAccountsInit', 'registration', $data.appId)
  }
  $stage = 'setting'
  # Reflection preserves the real WinRT getter exception instead of returning null.
  $setting = $notifier.GetType().GetProperty('Setting').GetValue($notifier)
  if ([string]$setting -ne 'Enabled') { @{status='disabled'} | ConvertTo-Json -Compress; exit }
  if ($data.operation -eq 'register') { @{status='registered'} | ConvertTo-Json -Compress; exit }
  $stage = 'xml'
  $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
  $xml.LoadXml($data.xml)
  $stage = 'toast'
  $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
  $toast.ExpirationTime = [DateTimeOffset]::Now.AddMinutes(5)
  $stage = 'show'
  $notifier.Show($toast)
  @{status='accepted'} | ConvertTo-Json -Compress
} catch {
  $notificationException = $_.Exception
  while ($notificationException.InnerException) { $notificationException = $notificationException.InnerException }
  @{status='failed'; stage=$stage; code=('0x{0:X8}' -f ($notificationException.HResult -band 0xffffffffL))} | ConvertTo-Json -Compress
}
'''


def _result(status):
    return {'ok': status in ('registered', 'accepted'), 'status': status, 'message': _MESSAGES[status]}


def toast_xml(title, body):
    for text in (title, body):
        if not isinstance(text, str) or not text.strip() or len(text) > 1000:
            raise ValueError('Invalid notification text')
        if any(ord(c) < 32 and c not in '\n\r\t' or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in (0xFFFE, 0xFFFF) for c in text):
            raise ValueError('Invalid XML character')
    toast = ET.Element('toast', {'duration': 'short'})
    binding = ET.SubElement(ET.SubElement(toast, 'visual'), 'binding', {'template': 'ToastGeneric'})
    ET.SubElement(binding, 'text').text = title
    ET.SubElement(binding, 'text').text = body
    return ET.tostring(toast, encoding='unicode')


def encoded_script(payload):
    data = base64.b64encode(json.dumps(payload, ensure_ascii=True).encode('utf-8')).decode('ascii')
    prefix = "$data = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + data + "')) | ConvertFrom-Json\n"
    return base64.b64encode((prefix + _SCRIPT).encode('utf-16le')).decode('ascii')


def parse_result(raw):
    try:
        value = json.loads(raw)
        status = value.get('status') if isinstance(value, dict) else None
        if status in _MESSAGES:
            result = _result(status)
            stage, code = value.get('stage'), value.get('code')
            if status == 'failed' and stage in ('registration', 'notifier', 'bootstrap', 'setting', 'xml', 'toast', 'show') and isinstance(code, str) and re.fullmatch(r'0x[0-9A-Fa-f]{8}', code):
                result['diagnostic'] = {'stage': stage, 'code': code.upper().replace('0X', '0x')}
                result['message'] += ' (' + stage + ' / ' + result['diagnostic']['code'] + ')'
            return result
    except (ValueError, TypeError):
        pass
    return _result('failed')


def _run(payload):
    if sys.platform != 'win32':
        return _result('unsupported')
    powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        completed = subprocess.run([str(powershell), '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded_script(payload)],
                                   capture_output=True, timeout=20, creationflags=0x08000000)
        if completed.returncode != 0:
            return _result('failed')
        return parse_result(completed.stdout.decode('utf-8-sig', errors='replace').strip())
    except subprocess.TimeoutExpired:
        return _result('timeout')
    except (OSError, ValueError):
        return _result('failed')


def register_notifications(executable=None, arguments=None, icon_path=None):
    """Explicit opt-in only. Creates/updates this user's AI Accounts shortcut.

    Frozen app defaults to its own exe. Source defaults to Python + GUI script.
    Registration submits and removes a suppressed first-use toast; it does not
    enable disabled Windows settings.
    """
    target = Path(executable or sys.executable).resolve()
    if not target.is_file():
        return _result('invalid')
    if arguments is None:
        arguments = [] if executable or getattr(sys, 'frozen', False) else [str(Path(__file__).with_name('windows_gui.py'))]
    if not isinstance(arguments, (list, tuple)) or any(not isinstance(a, str) or '\x00' in a for a in arguments):
        return _result('invalid')
    icon = Path(icon_path).resolve() if icon_path else target
    if not icon.is_file():
        return _result('invalid')
    return _run({'operation': 'register', 'appId': APP_ID, 'executable': str(target),
                 'arguments': subprocess.list2cmdline(arguments), 'icon': str(icon) + ',0'})


def send_notification(title, body):
    """Submit privacy-safe text; callers use provider/ordinal, never identity data.

    No implicit registration or permission changes. `ok` is submission only.
    """
    try:
        xml = toast_xml(title, body)
        # Defense in depth; caller must still compose only non-sensitive summaries.
        if re.search(r'@|\b(?:Bearer|sk-|eyJ)[A-Za-z0-9_\- .]*', title + ' ' + body):
            return _result('invalid')
    except (ValueError, TypeError):
        return _result('invalid')
    return _run({'operation': 'send', 'appId': APP_ID, 'xml': xml})
