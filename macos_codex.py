"""Select an installed, signed desktop/core pair before mutating account auth."""
import contextlib
import os
from pathlib import Path
import plistlib
import re
import shlex
import subprocess
import tempfile

class LaunchError(Exception):
    pass

# 0.167 is the desktop core verified with paginated sessions in this app.
MIN_CORE = (0, 167, 0)
REQUIREMENT = 'identifier "com.openai.codex" and anchor apple generic and certificate leaf[subject.OU] = "2DC432GLL2"'

def application_dirs():
    return [Path('/Applications'), Path.home() / 'Applications']

def verify_signature(app):
    return subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', '-R='+REQUIREMENT, str(app)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30).returncode == 0

def select_desktop(roots=None):
    candidates=[]
    for root in application_dirs() if roots is None else roots:
        for name in ('ChatGPT.app', 'Codex.app'):
            app=Path(root)/name
            try:
                with (app/'Contents/Info.plist').open('rb') as f:
                    info=plistlib.load(f)
                if info.get('CFBundleIdentifier') != 'com.openai.codex' or not verify_signature(app):
                    continue
                for relative in ('codex-cli/CodexCLI.app/Contents/MacOS/codex','codex'):
                    cli=app/'Contents/Resources'/relative
                    if not cli.is_file() or not os.access(cli,os.X_OK): continue
                    result=subprocess.run([str(cli),'--version'],capture_output=True,text=True,timeout=10)
                    match=re.fullmatch(r'codex-cli (\d+)\.(\d+)\.(\d+)(?:-([\w.]+))?\s*',result.stdout)
                    if result.returncode or not match: continue
                    core=tuple(map(int,match.group(1,2,3)))
                    if core < MIN_CORE: continue
                    # Prefer stable, then numeric alpha suffix; never lexical 9 > 10.
                    suffix=tuple(int(n) for n in re.findall(r'\d+',match.group(4) or ''))
                    build=int(info.get('CFBundleVersion','0'))
                    candidates.append(((*core,match.group(4) is None,suffix,build),app,cli))
            except (OSError,ValueError,plistlib.InvalidFileException,subprocess.SubprocessError):
                continue
    if not candidates:
        raise LaunchError('Update the official Codex desktop app before switching; no signed compatible desktop core was found. No account was changed.')
    _,app,cli=max(candidates,key=lambda row:row[0])
    return app,cli

@contextlib.contextmanager
def switch_tool_dir(app,cli,opener=Path('/usr/bin/open')):
    # CodexSwitch resolves codex from PATH. Intercept only its app subcommand;
    # other commands use the same verified desktop core, never a stale CLI.
    with tempfile.TemporaryDirectory(prefix='ai-accounts-codex-launch-') as temporary:
        directory=Path(temporary)
        command=directory/'codex'
        quote=shlex.quote
        command.write_text('#!/bin/sh\nset -eu\nif [ "${1-}" = app ]; then\n'
            +'  exec '+quote(str(opener))+' -a '+quote(str(app))+' --env '+quote('CODEX_CLI_PATH='+str(cli))+'\nfi\n'
            +'exec '+quote(str(cli))+' "$@"\n',encoding='utf-8')
        command.chmod(0o700)
        yield directory
