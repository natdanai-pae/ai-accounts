"""GUI lifecycle for the read-only snapshot subprocess (no persistent cache)."""
import json
import os
import subprocess
import threading
from mcp_server import ENDPOINT

class Bridge:
    def __init__(self,helper):self.helper=helper;self.process=None;self.endpoint=None
    def start(self):
        if self.process is not None:return
        self.process=subprocess.Popen([str(self.helper),'mcp-serve'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        process=self.process
        def ready():
            try:
                reply=json.loads(process.stdout.readline())
                if reply.get('endpoint')==ENDPOINT and process.poll() is None:self.endpoint=ENDPOINT
            except (ValueError,OSError):pass
        threading.Thread(target=ready,daemon=True).start()
    def stop(self):
        if self.process:
            self.process.stdin.close()
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:self.process.terminate()
        self.process=None;self.endpoint=None
    def publish(self,snapshot):
        if self.process and self.process.poll() is None:
            try:self.process.stdin.write(json.dumps(snapshot,ensure_ascii=True).encode()+b'\n');self.process.stdin.flush()
            except (OSError,ValueError):self.endpoint=None
    @property
    def running(self):return bool(self.endpoint and self.process and self.process.poll() is None)
