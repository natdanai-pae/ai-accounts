# AI Accounts 0.3.0 Beta

จัดการบัญชี Codex และ Claude หลายบัญชี เพิ่มบัญชีผ่านการเข้าสู่ระบบของผู้ให้บริการ อ่าน quota และแนะนำบัญชีแยกตามผู้ให้บริการโดยไม่สลับอัตโนมัติ รวม helper/runtime มาแล้ว ผู้ใช้ไม่ต้องติดตั้ง Python, Go หรือ Homebrew

> พักการดาวน์โหลดรุ่น Beta ชั่วคราวระหว่างปรับ UX/UI ตามผลตรวจ รุ่นนี้ยังไม่อนุมัติให้เผยแพร่

## ใช้โควตาให้คุ้มขึ้นอย่างไร

- **บัญชี 1, 2, 3 … จำง่าย** — เลขบัญชีคงเดิมเมื่อรีเฟรชยอด ไม่เรียงใหม่ตามโควตา
- **รู้ว่าควรใช้บัญชีไหนก่อน** — แถบแนะนำแยก Claude และ Codex พิจารณาโควตาที่เหลือกับเวลาถึงรีเซ็ต โดยคำนึงถึงรอบที่จำกัดการใช้งาน
- **เตือนให้กลับมาดูบัญชีที่เหมาะกว่า** — เมื่อเปิดแจ้งเตือน แอปเตือนเมื่อบัญชีแนะนำเปลี่ยน หรือรอบที่จำกัดจะรีเซ็ตภายใน 60 นาทีและยังเหลือโควตา ช่วยลดโควตาที่ไม่ได้ใช้ก่อนรีเซ็ต
- **ยอดและเวลารีเซ็ตอยู่ที่เดียว** — ดูเปอร์เซ็นต์คงเหลือและเวลานับถอยหลัง เปิดรายละเอียดเพื่อดูยอดอื่นที่ผู้ให้บริการส่งกลับมา

คำแนะนำเป็นการจัดลำดับจากข้อมูลที่มี ไม่ใช่การรับประกันความคุ้มค่าสูงสุดทุกงาน และไม่เพิ่มโควตา แอปไม่สลับบัญชีหรือกดใช้สิทธิ์รีเซ็ตเอง

### การแจ้งเตือนในรุ่นปรับปรุง

เปิดสวิตช์แจ้งเตือนในแอปก่อนใช้งาน ค่าเริ่มต้นปิดไว้ macOS ขอสิทธิ์ส่งแบนเนอร์และเสียง หากไม่ได้รับอนุญาตยังแสดงข้อความในแอป ส่วน Windows ใช้ข้อความในแอปและเสียง ยังไม่มี Windows toast

รีเฟรชทุก 5 นาทีเฉพาะขณะเปิดแอป แจ้งห่างกันอย่างน้อย 30 นาทีต่อบริการและจำเหตุการณ์เพื่อลดการแจ้งซ้ำ ข้อมูลเก่าหรืออ่านไม่ได้จะไม่ใช้แนะนำหรือแจ้งเตือน ไม่แสดงอีเมลในข้อความแจ้งเตือน

## macOS Apple Silicon

1. ดาวน์โหลด `AI-Accounts-0.3.0-macos-arm64.dmg` หรือ ZIP และตรวจ `SHA256SUMS` แพ็กเกจกำหนดขั้นต่ำ macOS 14 ไม่ใช่ Universal/Intel
2. เปิด DMG แล้วลาก `AI Accounts.app` ไป Applications หากใช้ ZIP ให้แตกไฟล์และย้ายแอปไป Applications ก่อน Setup ห้ามตั้ง background sync จากแอปบน DMG
3. แอปเซ็นแบบ ad-hoc ไม่มี Developer ID และยังไม่ notarize หาก macOS เตือน ให้ตรวจแหล่งดาวน์โหลดก่อนใช้ Open/Privacy & Security ตามขั้นตอนปกติ ห้ามปิด Gatekeeper
4. ติดตั้ง [Codex](https://chatgpt.com/codex) และ [Claude Desktop](https://claude.ai/download) จากผู้ให้บริการก่อนสลับบัญชี แอปเหล่านี้ไม่ได้รวมอยู่ในแพ็กเกจ

## Windows x64

1. ดาวน์โหลด `AI-Accounts-0.3.0-windows-x64.zip` และตรวจ `SHA256SUMS-windows` ไม่ใช่แพ็กเกจ Windows ARM64 native
2. เลือก Extract All แล้วเก็บทั้งโฟลเดอร์ `AI Accounts` เปิด `AI Accounts.exe` จากโฟลเดอร์ที่แตกแล้ว ห้ามย้ายเฉพาะ EXE เพราะต้องใช้ `backend`, `_internal`, `bin` และ assets ข้างกัน
3. แอปยังไม่มี Authenticode signature อาจมีคำเตือน SmartScreen ให้ตรวจแหล่งดาวน์โหลด/checksum และทำตามนโยบายเครื่อง ห้ามปิดระบบป้องกัน Windows
4. ติดตั้ง Codex และ Claude Desktop จากผู้ให้บริการ ปิด Codex ก่อนสลับบัญชีใน Windows; แอปจะไม่บังคับฆ่า process

## เริ่มใช้งาน

1. บัญชีที่มีใน codex-switch/claude-switcher จะถูกอ่านจาก metadata กดเพิ่มบัญชีเพื่อเปิดการเข้าสู่ระบบอย่างเป็นทางการ บัญชี Claude ที่เพิ่งเปิดหน้าต่างยังไม่ถือว่า login สำเร็จ
2. สำหรับ Claude ให้เข้าสู่ระบบ เปิดแท็บ Code หนึ่งครั้ง แล้วกด Connect/Setup การเชื่อม quota และการแชร์ Code session เป็นคนละส่วน; หากยังไม่มี Code session สามารถเชื่อม quota ได้โดยยังไม่เปิด sync
3. macOS อาจขอสิทธิ์ Keychain เมื่อกด Connect เพื่ออ่าน Claude Safe Storage ส่วน Windows ใช้ DPAPI ของผู้ใช้ปัจจุบัน ไม่รองรับ cookie แบบ App-Bound `v20`: หากพบจะหยุดพร้อมข้อความผิดพลาด ไม่ bypass การเข้ารหัส
4. บันทึกงานและอ่านคำยืนยันก่อนสลับบัญชี เพราะอาจปิดแอปที่กำลังทำงาน

Claude แชร์เฉพาะ local session ของแท็บ Code และ settings ที่ switcher รองรับ ไม่รวม Chats ปกติ, Cowork, มือถือ หรือ cloud การลบ session อาจส่งต่อไปบัญชีอื่นตาม sync เดิม จึงควรสำรองก่อนใช้งาน macOS ใช้ LaunchAgent หลัง Setup; Windows sync ขณะเปิด AI Accounts เท่านั้น ไม่มี background service เมื่อปิดแอป

ไม่มีประวัติ native ร่วมกันระหว่าง Codex กับ Claude การส่งบริบทข้ามผู้ให้บริการใช้ข้อความที่ผู้ใช้เลือกเขียนลง Markdown เท่านั้น ไม่อ่านหรือส่งออก transcript อัตโนมัติ

คำแนะนำใช้เปอร์เซ็นต์ที่เหลือต่อชั่วโมงจน reset แยกตามผู้ให้บริการ ไม่ใช่จำนวน token หรือการเทียบแพ็กเกจข้ามผู้ให้บริการ ข้อมูลเกิน 15 นาที ไม่ครบ หมด quota หรือหมดอายุจะไม่ถูกแนะนำ

## ข้อมูลส่วนตัว

ไม่มีบัญชีหรือ credential ของผู้พัฒนาอยู่ในแพ็กเกจ Connect/Refresh อาจติดต่อผู้ให้บริการด้วย session ของผู้ใช้

| ข้อมูล | macOS | Windows |
|---|---|---|
| Metadata | `~/Library/Application Support/AI Accounts` | `%LOCALAPPDATA%\AI Accounts` |
| Codex profiles | `~/.codex-switch` หรือ legacy `~/.codex-relay` | `%USERPROFILE%\.codex-switch` หรือ legacy `.codex-relay` |
| Claude config | `~/.config/claude-switcher/config.json` | `%USERPROFILE%\.config\claude-switcher\config.json` |
| Quota session | `~/.config/codexbar/config.json` | `%USERPROFILE%\.config\codexbar\config.json` |

ไฟล์ใหม่บน macOS ใช้สิทธิ์ 0600 และโฟลเดอร์ส่วนตัว 0700 Windows ใช้การป้องกันบัญชีผู้ใช้และ ACL ของตำแหน่งเก็บข้อมูล ไม่อ้างว่า POSIX permission เทียบเท่า Windows ACL อย่าแชร์ config หรือ backup เพราะอาจมี session

## Build และเครดิต

- macOS: Xcode Command Line Tools, Go และ Python build environment หรือ uv; รัน `bash package-release.sh` ใช้ CodexBar 0.84.0 และ Codex CLI 0.157.1 หาก CodexBar ในเครื่องไม่ตรงรุ่นจะดาวน์โหลดรุ่นที่ pin ไว้
- Windows: Python 3.12, Go, PyInstaller 6.22.3 และ cryptography 50.0.2; รัน `./build-windows.ps1` ใช้ Codex CLI 0.167.0 และ adapter quota ของ AI Accounts ไม่รวม CodexBar สำหรับ Windows
- CI ใช้ Python 3.12.10; local macOS build ใช้ 3.12.14 รายการ hash ของไฟล์จริงอยู่ใน `DEPENDENCY-SHA256SUMS`

ขอบคุณ [Claude Switcher — beyondworks](https://github.com/beyondworks/claude-switcher), [CodexSwitch — scwen](https://github.com/ScWen7/CodexSwitch), [CodexBar — Peter Steinberger](https://github.com/steipete/CodexBar) และ [OpenAI Codex](https://github.com/openai/codex) ดู [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md) และ license ที่รวมมากับแพ็กเกจ โครงการนี้ไม่ใช่ผลิตภัณฑ์อย่างเป็นทางการของ OpenAI หรือ Anthropic

ข้อจำกัด: ยังไม่ถือว่าทดสอบผ่านบน Mac/Windows เครื่องใหม่หรือบัญชีใหม่ทุกชนิด ไม่มีการทดสอบ login/switch จริงอัตโนมัติ การเปลี่ยน API/cookie อาจทำให้ Connect/usage ต้องปรับปรุง ผล fixture/CI ไม่เท่ากับการยืนยันการใช้งานจริง
