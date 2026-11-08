"""Build the BDA Thai quick guide. Fonts/logo supplied from the local brand assets."""
from pathlib import Path
import argparse
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.colors import HexColor

p = argparse.ArgumentParser()
p.add_argument('--fonts', required=True)
p.add_argument('--logo', required=True)
p.add_argument('--output', required=True)
a = p.parse_args()
for name, weight in [('Thai', 'Regular'), ('ThaiBold', 'Bold')]:
    pdfmetrics.registerFont(TTFont(name, str(Path(a.fonts) / f'Sarabun-{weight}.ttf'), shapable=True))
W, H = 595.28, 841.89
c = canvas.Canvas(a.output, pagesize=(W, H))
c.setTitle('AI Accounts | คู่มือใช้งาน macOS และ Windows | BDA')
c.setAuthor('BDA — Big Data Agency')
navy, blue, gold = '#2C3B4E', '#0085E8', '#F2B20A'

def text(s, x, y, width=499, size=12, bold=False, color=navy):
    q = Paragraph(s, ParagraphStyle('body', fontName='ThaiBold' if bold else 'Thai',
        fontSize=size, leading=size*1.55, textColor=HexColor(color), wordWrap='CJK', shaping=1))
    _, height = q.wrap(width, H)
    assert y + height < 781, (s, y, height)
    q.drawOn(c, x, H-y-height)
    return height

def page(n, kicker, title, subtitle):
    c.setFillColor(HexColor(navy)); c.rect(0, H-12, W, 12, fill=1, stroke=0)
    c.drawImage(a.logo, 48, H-101, 68, 68, preserveAspectRatio=True, mask='auto')
    text('BIG DATA AGENCY', 135, 43, size=10, bold=True)
    text('AI ACCOUNTS  /  USER GUIDE', 135, 61, size=9, color=blue)
    text(kicker, 48, 122, size=10, bold=True, color=blue)
    text(title, 48, 149, size=27, bold=True)
    text(subtitle, 48, 199, size=11, color='#637185')
    c.setStrokeColor(HexColor('#DDE4EC')); c.line(48, 57, W-48, 57)
    text('BDA  •  8 พฤศจิกายน 2569  •  Beta 0.3', 48, 792-30, size=8, width=430)
    c.setFont('ThaiBold', 10); c.drawRightString(W-48, 35, f'{n:02d} / 04')

def block(title, body, y):
    h = text(title, 48, y, size=15, bold=True)
    return y+h+8+text(body, 48, y+h+8, size=12)+21

page(1, '01 / START HERE', 'หลายบัญชี งานเดิม', 'คู่มือเริ่มต้นสำหรับ macOS และ Windows')
y = block('AI Accounts ช่วยอะไร', 'รวมบัญชี Claude และ Codex ไว้หน้าเดียว อ่านโควตาคงเหลือและเวลารีเซ็ต ช่วยเลือกบัญชีที่จะใช้ต่อ และจัดการการสลับบัญชีโดยให้ผู้ใช้ยืนยัน', 249)
y = block('เริ่มใช้ใน 3 ขั้นตอน', '<b>1  เชื่อมบัญชี</b> — ล็อกอินทีละบัญชี ตรวจอีเมลให้ตรง และเปิด Code สำหรับ Claude<br/><b>2  ดูยอดและเลือก</b> — รีเฟรช ตรวจโควตาและบัญชีที่แนะนำ<br/><b>3  ยืนยันสลับ</b> — รอให้งานจบ บันทึกงาน แล้วเปิด session เดิมเพื่อทำต่อ', y)
y = block('ขอบเขตของ session ร่วม', 'ใช้ประวัติร่วมระหว่างบัญชีของบริการเดียวกันบนเครื่องที่ตั้งค่าไว้ การมีไฟล์ประวัติเหมือนกันยังต้องตรวจว่างานเดิมเปิดต่อได้จริง<br/><b>Claude กับ Codex ไม่ได้ใช้ native session เดียวกัน</b> และการตั้งค่านี้ไม่ได้ซิงก์ระหว่าง Mac กับ PC ให้อัตโนมัติ', y)
text('โควตาในหน้านี้เป็นเปอร์เซ็นต์การใช้งาน ไม่ใช่ยอดเงิน และคำแนะนำไม่เพิ่มโควตาของผู้ให้บริการ', 48, y, size=10, color='#637185')
c.showPage()

page(2, '02 / CONNECT', 'ติดตั้งและเชื่อมบัญชี', 'เก็บการล็อกอินแยกกัน ตรวจด้วยอีเมลทุกครั้ง')
y = block('ติดตั้งตัวที่แจกให้ใช้งาน', '<b>Mac:</b> นำ AI Accounts.app ไปไว้ใน Applications แล้วเปิดจากตำแหน่งนั้น<br/><b>Windows:</b> แตกแพ็กเกจทั้งโฟลเดอร์ แล้วเปิด AI Accounts.exe เก็บโฟลเดอร์ backend, bin และ _internal ไว้ด้วย<br/>ติดตั้งแอป Claude / Codex ทางการแยกต่างหาก ตัวจัดการรวม runtime และ Claude Switcher มาแล้ว ไม่ต้องลง Python หรือ Go เพื่อใช้งาน', 249)
y = block('เพิ่มบัญชี Claude', 'กดเพิ่ม Claude → ล็อกอินด้วยอีเมลที่ต้องการ → เปิดแท็บ Code หนึ่งครั้ง → กลับ AI Accounts กดเชื่อมข้อมูลโควตา → ตรวจอีเมลและยอดบนการ์ด<br/>ทำทีละบัญชี หากรายการยังไม่เชื่อมให้ใช้ “เข้าสู่ระบบต่อ” บนรายการเดิม ไม่กดเพิ่มรายการซ้ำ', y)
y = block('เพิ่มบัญชี Codex', 'กดเพิ่ม Codex แล้วทำขั้นตอนล็อกอินของผู้ให้บริการให้เสร็จ กลับมารีเฟรชและตรวจอีเมลบนการ์ดก่อนใช้งาน หมายเลขบัญชีเป็นลำดับแสดงผล ไม่ใช่ตัวตนบัญชี', y)
text('Windows Store Claude เก็บข้อมูลในโฟลเดอร์แพ็กเกจของ Windows แอปต้องรองรับตำแหน่งนี้ ไม่ควรย้ายไฟล์ล็อกอินเองหรือคัดลอกทับอีกบัญชี', 48, y, size=10, color='#637185')
c.showPage()

page(3, '03 / CONTINUE WORK', 'สลับบัญชี ทำงานต่อ', 'เลือกจากข้อมูลล่าสุด และตรวจผลหลังสลับ')
y = block('ตั้งแชร์ session ของ Claude', 'เมื่อทุกบัญชีล็อกอินและเปิด Code แล้ว ให้สำรองข้อมูลและกด “แชร์เซสชัน” ระบบใช้โฟลเดอร์ Code ที่สร้างจริงของแต่ละบัญชี ต้องครอบคลุมทุกบัญชีที่ต้องการแชร์<br/>เปิด AI Accounts ค้างไว้ระหว่างใช้งานเพื่อให้การตรวจและซิงก์ทำงานตามรอบ', 249)
y = block('ก่อนและหลังสลับบัญชี', '<b>ก่อน:</b> รอให้งานที่กำลังตอบหรือรันคำสั่งจบ บันทึกงานและข้อความที่ยังไม่ได้ส่ง สำหรับ Claude บน Windows ให้เลือก File → Quit ก่อนสลับ ส่วน Codex ให้ปิดแอปตามที่หน้าจอแจ้ง<br/><b>สลับ:</b> กด “ใช้บัญชีนี้” ตรวจหมายเลขและอีเมลในคำยืนยัน<br/><b>หลัง:</b> เปิด Code และเลือก session เดิม ตรวจประวัติแล้วส่งคำสั่งทำงานต่อ หากเปิดไม่สำเร็จให้หยุดตรวจ ไม่สร้างงานใหม่ทับเพื่อแก้ปัญหา', y)
y = block('โหมดเลือกบัญชีในรุ่นที่มีเมนูนี้', '<b>ใช้เรียง:</b> เลือกหมายเลขแรกที่มีโควตาและข้อมูลพร้อม<br/><b>Balance:</b> เลือกบัญชีที่มีโควตาคงเหลือในรอบที่จำกัดมากกว่า<br/><b>ตามโควตา / รีเซ็ต:</b> พิจารณาโควตาที่เหลือเทียบเวลาถึงรีเซ็ตและความพร้อมใช้งาน คำนวณแยก Claude กับ Codex', y)
text('คำแนะนำเป็นแนวทางจากข้อมูลที่มี ไม่รับประกันว่าเหมาะที่สุดทุกงาน ข้อมูลเก่าหรืออ่านไม่สำเร็จไม่ควรใช้ตัดสินใจสลับ', 48, y, size=10, color='#637185')
c.showPage()

page(4, '04 / LIMITS & RECOVERY', 'โควตา แจ้งเตือน และกู้คืน', 'ใช้งานอย่างเข้าใจสถานะของรุ่น Beta')
y = block('ดูยอดและเวลารีเซ็ต', 'รีเฟรชเพื่อดูเปอร์เซ็นต์คงเหลือของรอบหลักและรายสัปดาห์ พร้อมเวลานับถอยหลัง ผู้ให้บริการอาจส่งข้อมูลมาไม่ครบ ให้ดูสถานะบนการ์ด ไม่ตีความข้อมูลที่หายว่าเหลือ 0%', 249)
y = block('การแจ้งเตือนและรีเซ็ตฟรี', 'ในรุ่นที่มีตัวเลือกใหม่ เปิดแจ้งเตือนเมื่อใช้ถึง 50% ของแต่ละรอบและเมื่อบัญชีแนะนำเปลี่ยน ต้องเปิดแอปค้างไว้ และระบบปฏิบัติการต้องอนุญาตการแจ้งเตือน<br/>Codex: ใช้สิทธิ์รีเซ็ตได้เมื่อแอปตรวจพบสิทธิ์ที่รองรับและยืนยันแล้วเท่านั้น ตั้งงดแนะนำใช้สิทธิ์เมื่อรอบที่จำกัดใกล้รีเซ็ตภายใน 2 วัน แอปไม่ซื้อเครดิตหรือรีเซ็ตเอง<br/>Claude: ยังไม่รองรับการกดใช้สิทธิ์รีเซ็ตจากแอปนี้', y)
y = block('เมื่อเชื่อมไม่ได้ / session ไม่มา', 'ตรวจอีเมลบนการ์ดก่อน → ใช้รายการเดิมเข้าสู่ระบบต่อ → เปิด Code → เชื่อมข้อมูลใหม่ หากแจ้งว่าไฟล์ถูกล็อกให้ออกจาก Claude ตามปกติหลังงานจบ<br/>หาก session ไม่ตรง ให้หยุดสลับและเก็บสำรองไว้ ตรวจโฟลเดอร์และผลซิงก์ก่อนกู้คืน อย่าลบโปรไฟล์หรือคัดลอก token ข้ามบัญชี', y)
text('<b>ข้อจำกัดรุ่นนี้:</b> การแจ้งเตือน Windows ยังไม่ยืนยันว่าแสดง banner ได้ และ Mac ที่ติดตั้งอยู่เดิมอาจยังไม่มีเมนูใหม่ครบ คู่มือนี้ไม่ใช่หลักฐานว่าทุกฟังก์ชันผ่านบนทุกเครื่อง ดูผลทดสอบแยกประกอบก่อนเผยแพร่รุ่นติดตั้ง', 48, y, size=10, color='#637185')
text('เครดิต: Claude Switcher (beyondworks), CodexSwitch (ScWen7), CodexBar (steipete), OpenAI Codex และผู้พัฒนา runtime — รายละเอียดใน THIRD-PARTY-NOTICES.md', 48, 711, size=9, color='#637185')
text('<link href="https://github.com/natdanai-pae/ai-accounts" color="#0085E8">github.com/natdanai-pae/ai-accounts</link>', 48, 744, size=9)
c.save()
