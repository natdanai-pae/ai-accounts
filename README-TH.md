# AI Accounts 0.3.0 Beta

แอป macOS สำหรับ Apple Silicon จัดการบัญชี Codex และ Claude หลายบัญชี พร้อมแสดง quota และคำแนะนำที่ไม่สลับบัญชีอัตโนมัติ

1. เปิด DMG และลาก AI Accounts ไป Applications แอปนี้เป็น beta ที่เซ็นแบบ ad-hoc เท่านั้น ยังไม่มี Developer ID และยังไม่ผ่าน notarization ตรวจแหล่งดาวน์โหลดและ SHA256SUMS ก่อนเปิด ใช้คำสั่ง Open/Privacy & Security ของ macOS ตามปกติเมื่อระบบอนุญาต ห้ามปิด Gatekeeper
2. ติดตั้งแอป Codex และ Claude จากผู้ให้บริการก่อนใช้งาน แอปนี้รวม runtime ของ helper และ quota CLI แล้ว ไม่ต้องติดตั้ง Homebrew หรือ Python
3. บัญชีที่มีใน codex-switch/claude-switcher จะถูกอ่านจาก metadata กดเพิ่มบัญชีเพื่อเปิดการเข้าสู่ระบบอย่างเป็นทางการ สำหรับ Claude ให้เข้าสู่ระบบและเปิดแท็บ Code หนึ่งครั้ง จากนั้นกด Connect และ Setup
4. Connect อาจขอสิทธิ์ Keychain เพื่ออ่าน Claude Safe Storage และบันทึก session สำหรับอ่าน quota ในไฟล์ส่วนตัว สิทธิ์ไฟล์ 0600 โฟลเดอร์ 0700 ไม่มี credential อยู่ในไฟล์เผยแพร่
5. การสลับบัญชีอาจปิดแอปที่กำลังทำงาน โปรดบันทึกงานและอ่านคำยืนยันก่อนสลับ สำหรับ Claude แชร์เฉพาะ local session ของแท็บ Code และ settings ที่ switcher รองรับ ไม่รวม Chats ปกติ, Cowork, มือถือ หรือ cloud การลบ session อาจถูกส่งต่อไปบัญชีอื่นตามกลไก sync เดิม จึงควรสำรองก่อนใช้งาน ไม่ใช่ประวัติร่วมระหว่าง Codex กับ Claude

คำแนะนำใช้เปอร์เซ็นต์ที่เหลือต่อชั่วโมงจน reset แยกตามผู้ให้บริการ ไม่ใช่จำนวน token ข้อมูลที่เก่า ไม่ครบ หรือหมดอายุจะไม่ถูกแนะนำ การส่งบริบทข้ามผู้ให้บริการทำได้ด้วยข้อความที่ผู้ใช้เลือกเขียนลง Markdown เท่านั้น

การ build: macOS Apple Silicon พร้อม Xcode Command Line Tools, Go, uv และ Python 3.12 build environment ที่มี PyInstaller 6.22.3 / cryptography 50.0.2 ใช้ `package-release.sh` โดยมี source MIT ของ CodexSwitch และ CodexBar 0.84.0 ที่ตรวจสอบแล้ว รวมถึง Codex CLI 0.157.1 ในเครื่อง build; ไม่มีข้อมูลบัญชีผู้ build ถูกคัดลอก

ข้อจำกัดที่ยังไม่ตรวจ: ไม่ทดสอบสลับบัญชีจริงหรือเข้าสู่ระบบจริงอัตโนมัติ และยังไม่ถือว่าผ่านการทดสอบบน Mac เครื่องใหม่ การเปลี่ยน API/cookie ของผู้ให้บริการอาจทำให้ Connect/usage ต้องปรับปรุง
