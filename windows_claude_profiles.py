"""Checkpoint primary-app authentication; leave all work/session folders in place."""
import os
from pathlib import Path
import shutil
import stat
import subprocess
import re
import uuid

from backend import SafeError, atomic_json, read_json, valid_key

AUTH_ITEMS = ('Local State', 'Network', 'Local Storage', 'Session Storage', 'config.json')


class AuthStore:
    def __init__(self, live, root):
        self.live, self.root = Path(live), Path(root)
        self.journal = self.root / 'switch-in-progress.json'

    @staticmethod
    def is_link(path):
        if path.is_symlink():
            return True
        return os.name == 'nt' and path.exists() and bool(path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)

    def check_tree(self, path):
        if self.is_link(path):
            raise SafeError('Refusing linked Claude authentication data')
        if path.is_dir():
            for parent, directories, files in os.walk(path, followlinks=False):
                for name in directories + files:
                    if self.is_link(Path(parent) / name):
                        raise SafeError('Refusing linked Claude authentication data')

    def prepare(self):
        for path in (self.live, self.root):
            for parent in (path, *path.parents):
                if self.is_link(parent):
                    raise SafeError('Refusing linked Claude profile storage')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not (self.root / 'protected').exists():
            if os.name == 'nt':
                # Snapshots contain sign-in data; no inherited access for other users.
                output = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'], capture_output=True, check=True, creationflags=0x08000000).stdout
                sid = re.search(rb'S-1-5-[0-9-]+', output).group().decode('ascii')
                result = subprocess.run(['icacls', str(self.root), '/inheritance:r', '/grant:r', f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F'], capture_output=True, creationflags=0x08000000)
                if result.returncode:
                    raise SafeError('Could not protect Claude sign-in backups')
            (self.root / 'protected').write_text('current-user-and-system', encoding='ascii')

    def state(self):
        return read_json(self.root / 'state.json', {'active': None, 'snapshots': {}})

    def copy_item(self, source, destination):
        self.check_tree(source)
        if destination.exists():
            raise SafeError('Refusing to overwrite existing Claude checkpoint data')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, copy_function=shutil.copy2)
        else:
            shutil.copy2(source, destination)

    def checkpoint(self, destination):
        destination.mkdir(parents=True)
        for name in AUTH_ITEMS:
            source = self.live / name
            if source.exists():
                self.copy_item(source, destination / name)

    def capture(self, key):
        valid_key(key)
        self.prepare()
        if self.journal.exists():
            raise SafeError('Finish restoring the interrupted Claude switch first')
        snapshot = f'{key}-{uuid.uuid4().hex}'
        self.checkpoint(self.root / 'snapshots' / snapshot)
        state = self.state()
        state['snapshots'][key] = snapshot
        state['active'] = key
        atomic_json(self.root / 'state.json', state)

    def relocate(self, source, destination):
        # Only fixed auth items inside the checked live root may be moved.
        if source.parent.resolve() != self.live.resolve() or source.name not in AUTH_ITEMS:
            raise SafeError('Claude authentication move is outside the primary profile')
        if not destination.resolve().is_relative_to(self.root.resolve()):
            raise SafeError('Claude backup destination is outside protected storage')
        self.check_tree(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)

    def recover(self):
        if not self.journal.exists():
            return
        self.prepare()
        record = read_json(self.journal, {})
        transaction = self.root / 'transactions' / record['transaction']
        if transaction.parent.resolve() != (self.root / 'transactions').resolve() or not (transaction / 'rollback').is_dir():
            raise SafeError('Claude rollback data is missing; originals were retained')
        for name in AUTH_ITEMS:
            current = self.live / name
            if current.exists():
                self.relocate(current, transaction / ('recovery-' + uuid.uuid4().hex) / name)
            original = transaction / 'rollback' / name
            if original.exists():
                self.copy_item(original, current)
        atomic_json(self.root / 'state.json', record['previous'])
        self.journal.rename(transaction / ('recovered-' + uuid.uuid4().hex + '.json'))

    def activate(self, key):
        valid_key(key)
        self.prepare()
        self.recover()
        state = self.state()
        if state['active'] == key:
            return
        snapshot = state['snapshots'].get(key)
        source = self.root / 'snapshots' / snapshot if snapshot else None
        if source and (source.parent.resolve() != (self.root / 'snapshots').resolve() or not source.is_dir()):
            raise SafeError('Saved Claude authentication checkpoint is missing')
        transaction_id = uuid.uuid4().hex
        transaction = self.root / 'transactions' / transaction_id
        self.checkpoint(transaction / 'rollback')
        atomic_json(self.journal, {'transaction': transaction_id, 'previous': state, 'target': key})
        try:
            for name in AUTH_ITEMS:
                current = self.live / name
                if current.exists():
                    self.relocate(current, transaction / 'displaced' / name)
                incoming = source / name if source else None
                if incoming and incoming.exists():
                    self.copy_item(incoming, current)
            state['active'] = key
            atomic_json(self.root / 'state.json', state)
            self.journal.rename(transaction / 'completed.json')
        except Exception as error:
            details = {'type': type(error).__name__, 'errno': getattr(error, 'errno', None), 'winerror': getattr(error, 'winerror', None)}
            atomic_json(self.root / 'last-error.json', details)
            try:
                self.recover()
            except Exception as recovery:
                details['recovery_type'] = type(recovery).__name__
                details['recovery_winerror'] = getattr(recovery, 'winerror', None)
                atomic_json(self.root / 'last-error.json', details)
                raise SafeError('สลับข้อมูลไม่ได้ สำเนาบัญชีเดิมยังอยู่และรอกู้คืน · Windows error ' + str(details['winerror'])) from None
            raise SafeError('สลับข้อมูลไม่ได้ กู้บัญชีเดิมกลับแล้ว · Windows error ' + str(details['winerror'])) from None
