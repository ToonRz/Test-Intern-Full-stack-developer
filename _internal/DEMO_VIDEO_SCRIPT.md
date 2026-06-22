# 🎬 Demo Video Script — Log Management System

> **เป้าหมาย**: สาธิตระบบให้กรรมการเห็นว่า **ครบ spec และใช้งานได้จริง** ภายใน 30 นาที
> **Format**: Screen recording + voiceover (ไทยคละอังกฤษตามถนัด)
> **Pre-flight**: รัน checklist หัวข้อ "เตรียมการก่อนบันทึก" ก่อนกด Record ทุกครั้ง

> **สำหรับผู้อัดคลิป**:
> - `# 🎙️ ...` = บรรทัดที่ต้อง **พูด** (อ่านออกเสียง)
> - `# 💻 Terminal:` = **คำสั่ง** ที่ต้องพิมพ์/วาง (comment บอกผลที่คาดหวังไว้ข้างล่าง)
> - `# 🖱️ Click:` = **สิ่งที่ต้องคลิก** ในหน้าเว็บ/Postman
> - `# 📺 Cut:` = จุดตัดคลิป (ใช้ตอน edit)
> - `# ⏱️ ...` = หมายเหตุจังหวะเวลา/จังหวะพูด
> - บรรทัดอื่น = คำอธิบาย/หมายเหตุ ไม่ต้องอ่าน

---

## 🎯 TL;DR — สิ่งที่กรรมการจะได้เห็น

1. Stack ขึ้นครบ 5 services ด้วยคำสั่งเดียว (`make up`)
2. Login + RBAC ทำงานจริง — Admin เห็นทุก tenant, Viewer เห็นแค่ของตัวเอง
3. Ingest 4+ sources: Syslog UDP/TCP, HTTP API, JSON batch, simulator (6 sources)
4. Search + Dashboard + Filter + Charts ครบ
5. Brute-Force Alert ยิงจริง — 5 failed logins ใน 5 นาที = alert
6. Rate Limit ป้องกัน brute force ที่ login (429 ที่ attempt ที่ 6)
7. Security hardening: HTTPS + HSTS + HttpOnly cookie + bcrypt + constant-time login
8. Tests 91/91 ผ่าน + Postman collection + Helm/Terraform + OpenTelemetry
9. **Highlight**: race-safe alert engine ด้วย FOR UPDATE lock

---

## 🛠️ เตรียมการก่อนบันทึก (Pre-flight)

```bash
# 💻 Terminal — รันทั้งหมดนี้ก่อนกด Record (เรียงตามลำดับ):
cd /Users/narawich/Documents/GitHub/Test-Intern-Full-stack-developer

# 1. Stack ต้อง up ครบ (5 services)
docker compose ps
#    คาดหวัง: backend/frontend/nginx/postgres/redis ทุกตัว "Up (healthy)"

# 2. ล้าง log + alert เก่า → demo สดๆ
docker compose exec -T postgres psql -U postgres -d logs \
  -c "TRUNCATE logs, triggered_alerts RESTART IDENTITY;"

# 3. Restart backend → re-seed alert rule (สำคัญ! เพราะ TRUNCATE ลบ rule ไปด้วย)
docker compose restart backend
sleep 5

# 4. ทดสอบ 1 ingest → ยืนยันทุกอย่างทำงาน
curl -sk -X POST https://localhost/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"tenant":"demoA","source":"api","event_type":"smoke_test","severity":1}' \
  | python3 -m json.tool
#    คาดหวัง: {"status":"ok","ingested":1,"logs":[{"id":1,...}]}

# 5. ดู TLS cert ยังไม่หมดอายุ
echo | openssl s_client -connect localhost:443 -servername localhost 2>/dev/null \
  | openssl x509 -noout -dates
#    คาดหวัง: notAfter=... 2027 (valid 1 ปี)
```

### Setup Postman ให้พร้อม (ทำครั้งเดียวก่อนอัด)

```
# 🖱️ Postman setup:
1. Import → File → เลือก api_collection.json (เวอร์ชันที่แก้ schema v2.1 แล้ว)
2. Environments → + Create new
   - Name:        Log Management Local
   - baseUrl:     https://localhost
   - token:       (เว้นว่าง — Login จะ set ให้อัตโนมัติผ่าน test script)
3. มุมขวาบน dropdown → เลือก environment "Log Management Local"
4. Settings → General → SSL certificate verification = OFF
5. Auth → Login → Send → ดู Console: "✓ login OK, token saved"
```

### Window layout ที่แนะนำ

```
# 🖥️ จอซ้าย:    Chrome — Frontend (https://localhost/)
# 🖥️ จอกลาง:    Postman (collection "Log Management System API" เปิดค้าง)
# 🖥️ จอขวา:    Terminal — split 2 panes
#               - pane บน: docker compose logs -f backend | grep --line-buffered -E "POST|alert"
#               - pane ล่าง: commands
# 📺 OBS: จับ 3 จอนี้พร้อมกัน หรือสลับ scene ตาม section
```

### Audio / Video tips

```
# 🎙️ Audio:
- ใช้ headset mic (ไม่ใช่ mic notebook)
- ตัด background noise: Krisp (free) / RTX Voice / OBS noise suppression filter
- ระยะ mic ห่างปาก 1 ฝ่ามือ

# 📺 Recording:
- OBS Studio (free) หรือ Loom
- Resolution: 1920×1080, 30 fps
- Bitrate: 4-6 Mbps สำหรับ 1080p
- Format: MP4 (H.264) หรือ MKV แล้ว remux
- ซ้อน webcam มุมขวาล่าง เพิ่มความเป็น presenter
```

---

## 📜 Script (30 นาที)

---

### ⏱️ [0:00–2:00] Opening Hook — ทำไมต้องดูคลิปนี้

> **🎙️ พูด** (พูดช้าๆ ชัดๆ ดูกล้อง): "ถ้าคุณเป็น Security Analyst ที่ต้องตรวจ log จาก Firewall, Cloud, AD, API หลายสิบแหล่งทุกวัน — คุณจะใช้เวลาเท่าไหร่? วันนี้ผมจะแสดงให้เห็นว่าระบบที่ผมพัฒนาช่วยให้คุณ ingest จาก 6 แหล่ง ค้นหาใน 1 วินาที และแจ้งเตือนภัยคุกคามอัตโนมัติ — ภายใน 30 นาที"

> **🎙️ พูด**: "ระบบชื่อ **Log Management System** ตามสเปค 12 ข้อ — และทุกฟีเจอร์ทำงานจริง ไม่ใช่ mockup"

# 📺 Cut → transition slide หรือ title card 2 วินาที

---

### ⏱️ [2:00–5:00] Section 1 — Architecture & Stack Overview

> **🎙️ พูด**: "มาดูภาพรวมก่อน — ระบบนี้ออกแบบเป็น **5 services** ตามแนวคิด microservice ขนาดเล็ก"

```bash
# 💻 Terminal — โชว์ว่าทุกอย่างรันอยู่ (อย่าพูดเงียบ อธิบายทีละตัว):
docker compose ps
```

> **🎙️ พูด** (ชี้ทีละบรรทัด): "**Postgres** เก็บ log, **Redis** cache enrichment, **Backend** เป็น FastAPI ประมวลผล, **Frontend** เป็น React แสดงผล, และ **Nginx** ทำหน้าที่ TLS termination กับ Syslog proxy — ครบเซ็ตในคำสั่งเดียว"

> **🎙️ พูด**: "ตามสเปคข้อ 9 ระบบรันได้ 2 โหมด — **Appliance** สำหรับ on-prem ด้วย Docker Compose และ **SaaS** สำหรับ Cloud ด้วย Helm บน Kubernetes"

# 🖱️ Click: เปิด `docs/architecture.md` (หรือ slide)

> **🎙️ พูด**: "หัวใจของระบบคือ **normalized schema** ในสเปคข้อ 3 — log จากทุก source จะถูกแปลงเป็น schema เดียวก่อนเก็บ ทำให้ค้นหาและแจ้งเตือนได้แบบไม่สนใจที่มา"

```bash
# 💻 Terminal — โชว์ schema หลัก:
head -50 backend/models/schemas.py | grep -A 25 "class NormalizedLog"
```

> **🎙️ พูด**: "เห็นไหมครับ — มี field ครบตามสเปค: @timestamp, tenant, source, severity, action, src_ip, geo enrichment, raw payload — schema นี้ทุก log ทุกแหล่งต้อง normalize เข้ามา"

---

### ⏱️ [5:00–7:00] Section 2 — Bring Up the Stack

> **🎙️ พูด**: "ข้อได้เปรียบของ Appliance mode คือเปิดได้ด้วยคำสั่งเดียว"

```bash
# 💻 Terminal — ถ้าเริ่ม clean:
make up
# ระหว่างรอ พูดถึง: "ขั้นตอนนี้จะ generate TLS cert, build images, start 5 services"
```

> **🎙️ พูด**: "ขั้นตอนเดียวเสร็จเลย — TLS cert, Postgres, Redis, Backend, Frontend, Nginx พร้อมหมดภายใน 1-2 นาที"

ถ้า stack รันอยู่แล้ว (กรณี demo รอบ 2):

```bash
# 💻 Terminal — โชว์ health check + log สั้นๆ:
curl -sk https://localhost/health
# {"status":"healthy"}

docker compose logs backend | grep -i startup
```

> **🎙️ พูด**: "ตัว backend มี lifespan startup ที่ทำ 3 อย่าง — initialize database connection pool, seed demo users, และ retry pending alert deliveries ที่ค้างจาก restart ครั้งก่อน"

---

### ⏱️ [7:00–10:00] Section 3 — Login + Security Headers

# 🖱️ Click: เปิด tab ใหม่ → `https://localhost/` (เน้น HTTPS)

> **🎙️ พูด**: "สังเกตว่า URL เป็น **HTTPS** ทันที ไม่ใช่ HTTP — Nginx ทำ TLS termination และบังคับ redirect HTTP→HTTPS"

# 🖱️ Click: คลิกปุ่ม "admin" ในส่วน "Demo accounts (dev only)" → คลิก "Sign in"

> **🎙️ พูด**: "Login สำเร็จ — แต่สังเกตว่า **ไม่มี JWT อยู่ใน localStorage** นะครับ ดูได้"

# 🖱️ Click: DevTools (F12) → Application → Cookies

> **🎙์ พูด**: "Cookie ชื่อ access_token มี flag **HttpOnly** หมายความว่า JavaScript ในหน้าเว็บอ่านไม่ได้เลย — XSS payload ขโมย token ไม่ได้"

```bash
# 💻 Terminal — พิสูจน์ด้วย curl ว่า Set-Cookie มี flag ครบ:
# ใช้ -D - -o /dev/null เพื่อ dump headers โดยไม่ทิ้ง body (ห้ามใช้ -I เพราะมันบังคับ HEAD request ทำให้ไม่เห็น Set-Cookie)
curl -sk -D - -o /dev/null -X POST https://localhost/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | grep -i "set-cookie"
# คาดหวัง: ... HttpOnly; Max-Age=3600; Path=/api/v1; SameSite=lax
```

> **🎙์ พูด**: "ครบชุด — **HttpOnly + Secure + SameSite=Lax + Path=/api/v1** — ปิด 3 ช่องโจมตี XSS, CSRF, mixed-content"

```bash
# 💻 Terminal — โชว์ security headers:
curl -skI https://localhost/ | grep -iE "strict-transport|x-frame|content-security|referrer|x-content"
```

> **🎙️ พูด**: "นี่คือ defense-in-depth — HSTS, X-Frame-Options DENY (กัน clickjacking), X-Content-Type-Options nosniff, Referrer-Policy — ครบทุก header ที่ security checklist แนะนำ"

---

### ⏱️ [10:00–15:00] Section 4 — Ingestion Demo (4+ Sources)

> **🎙️ พูด**: "ตอนนี้มาดูหัวใจของระบบ — **การ ingest log จากหลายแหล่ง** ตามสเปคข้อ 2 และข้อ 4"

#### Source 1 — Syslog UDP (firewall)

```bash
# 💻 Terminal — ยิง firewall syslog ผ่าน UDP 514:
echo '<134>Jun 22 10:00:00 fw01 vendor=demo product=ngfw action=deny src=10.0.1.10 dst=8.8.8.8 spt=5353 dpt=53 proto=udp msg="DNS blocked" policy=Block-DNS' \
  | nc -u -w1 localhost 514
```

> **🎙์ พูด**: "ข้อความนี้ถูกส่งผ่าน UDP port 514 — Nginx stream block forward ไปยัง backend listener ที่ใช้ asyncio loop.add_reader — ไม่ block event loop แม้จะมี log หลายพันบรรทัดต่อวินาที"

```bash
# 💻 Terminal — ยืนยันว่า log เข้า database (ดู row ล่าสุด + parsed fields):
docker compose exec -T postgres psql -U postgres -d logs \
  -c "SELECT id, src_ip, action, vendor, product, timestamp FROM logs WHERE source='firewall' ORDER BY id DESC LIMIT 1;"
#    คาดหวัง: id=14 | 10.0.1.10 | deny | demo | ngfw | 2026-06-22 10:00:00+00
```

> **🎙️ พูด**: "เห็นไหมครับ — row ใหม่โผล่ทันที ไม่ต้องรอ — backend เขียน async ลง Postgres JSONB column แล้ว frontend ดึงจาก API `/api/v1/logs` อีกที"

#### Source 2 — Syslog TCP (router)

```bash
# 💻 Terminal — script ตัวอย่างที่รวม 7 บรรทัด UDP + TCP framing:
bash samples/send_syslog.sh localhost 514
#    คาดหวัง: "Done! Sent 7 syslog messages (3 UDP + 4 TCP)"
```

> **🎙์ พูด**: "TCP ก็รับเหมือนกัน — backend auto-detect ทั้ง RFC6587 octet-counted framing และ LF-delimited framing ไม่ต้องบอกล่วงหน้า"

```bash
# 💻 Terminal — ยืนยันว่าทั้ง 2 framing ของ TCP เข้า DB:
docker compose exec -T postgres psql -U postgres -d logs \
  -c "SELECT id, source, vendor, raw->>'original' FROM logs WHERE raw->>'original' LIKE '%link-up%' OR raw->>'original' LIKE '%Threat-blocked%' ORDER BY id DESC LIMIT 3;"
#    คาดหวัง: เห็นทั้ง network (router, octet-counted) และ firewall (LF-delimited)
```

#### Source 3 — HTTP POST /ingest (Postman)

# 🖱️ Click: Postman → Ingest → "POST Single Log" → Send

```json
{
  "tenant": "demoA",
  "source": "api",
  "event_type": "app_login_failed",
  "user": "alice",
  "src_ip": "203.0.113.7"
}
```

> **🎙️ พูด**: "HTTP API ก็ได้ — body เป็น JSON object เดียว แต่ถ้าส่งเป็น JSON array ก็ ingest ได้พร้อมกันหลายรายการ"

#### Source 4 — HTTP POST /ingest (batch array)

# 🖱️ Click: Postman → Ingest → "POST Batch Logs" → Send

> **🎙️ พูด**: "Endpoint เดียวกัน รับ array ได้ — backend ใช้ async loop ประมวลผลทีละ log พร้อม enrichment ทุกตัว"

#### Source 5 — JSON Batch Files (AWS/M365/AD)

# 🖱️ Click: Postman → Ingest → "POST Batch Files (AWS/M365/AD)" → Send

> **🎙️ พูด**: "อันนี้สำหรับ AWS CloudTrail, M365, AD ที่ต้อง upload หลายไฟล์พร้อมกัน — ใช้ endpoint /ingest/batch"

#### Source 6 — Simulator script (ทุก source ในคำสั่งเดียว)

```bash
# 💻 Terminal — script ตัวอย่างที่รวม 6 แหล่ง (HTTP):
python3 samples/post_logs.py https://localhost/api/v1/ingest
#    คาดหวัง: 18 logs ingested, ครอบคลุม api/crowdstrike/aws/m365/ad
```

> **🎙️ พูด**: "และนี่คือ simulator ที่ส่งตัวอย่างจาก **6 แหล่ง** ตามสเปคข้อ 4.3-4.7 — CrowdStrike, AWS CloudTrail, M365, Active Directory, Firewall, API — ครบทุกตัว"

```bash
# 💻 Terminal — ดูว่า log ทั้งหมดเข้าจริง:
docker compose exec -T postgres psql -U postgres -d logs \
  -c "SELECT source, COUNT(*) FROM logs GROUP BY source ORDER BY 2 DESC;"
#    คาดหวัง: แถวของ api, firewall, network, aws, crowdstrike, m365, ad
```

> **🎙️ พูด**: "ครบ — log เข้าจริงทุก source"

---

### ⏱️ [15:00–18:00] Section 5 — Search & Dashboard

# 🖱️ Click: กลับไป Frontend → คลิกเมนู "Dashboard"

> **🎙️ พูด**: "Dashboard แสดง 4 อย่างตามสเปคข้อ 7 — Top N IPs/Users/Events, Timeline, Pie chart by Source และตัวกรอง tenant/source/time"

# 🖱️ Click: เปลี่ยน time range จาก "Last 24h" → "Last 7 days"

> **🎙️ พูด**: "Filter time range ทำงานแบบ real-time — backend รับ query param `start`, `end` แล้ว query Postgres JSONB index"

# 🖱️ Click: เมนู "Log Search"

> **🎙️ พูด**: "หน้า Log Search ค้นหาแบบ full-text พร้อม pagination, filter chips, และ expandable raw JSON"

# 🖱️ Click: พิมพ์ "192.0.2" ในช่อง search → รอ 300ms

> **🎙์ พูด**: "Search มี **debounce 300ms** กัน spam request — และที่สำคัญคือ escape wildcard `%` `_` `\` ก่อน query ป้องกัน LIKE injection"

```bash
# 💻 Terminal — โชว์ raw API:
TOKEN=$(curl -sk -X POST https://localhost/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://localhost/api/v1/logs?source=firewall&size=3" | python3 -m json.tool | head -40
```

> **🎙️ พูด**: "นี่คือสิ่งที่ Frontend เรียก — JSON ตรงๆ พร้อม geo enrichment ที่ backend เพิ่มให้อัตโนมัติ"

---

### ⏱️ [18:00–22:00] Section 6 — Alert Engine Demo (สำคัญที่สุด!)

> **🎙️ พูด**: "มาถึงฟีเจอร์ที่สำคัญที่สุด — **Alert Engine** ที่ทำงานแบบ real-time"

# 🖱️ Click: เมนู "Alert Rules"

> **🎙️ พูด**: "มี rule 'Login Failed Brute-Force' ที่ seed มาตอน backend boot — เงื่อนไขคือ 5 failed login ใน 5 นาที จาก src_ip เดียวกัน — ถ้าครบ alert จะถูกสร้างทันที"

#### Step 1 — Trigger Brute-Force

```bash
# 💻 Terminal — ยิง 6 failed login จาก IP เดียวกัน:
for i in 1 2 3 4 5 6; do
  curl -sk -X POST https://localhost/api/v1/ingest \
    -H "Content-Type: application/json" \
    -d "{\"tenant\":\"demoA\",\"source\":\"api\",\"event_type\":\"app_login_failed\",\"user\":\"victim_$i\",\"src_ip\":\"203.0.113.99\",\"rule_name\":\"Login Failed\",\"severity\":7,\"action\":\"deny\"}" \
    | python3 -c "import json,sys;d=json.load(sys.stdin);print(f'  attempt $i: ingested={d.get(\"ingested\",0)}')"
done
```

> **🎙️ พูด** (ระหว่างรอ): "แต่ละ log ที่เข้ามา backend จะ schedule background task ตรวจ alert — ใช้ Postgres `FOR UPDATE` lock ป้องกัน race condition แม้ 2 requests มาพร้อมกัน alert จะถูกสร้างแค่ 1 อัน"

#### Step 2 — ดู Alert โผล่

# 🖱️ Click: เมนู "Triggered" → รอ 2-3 วินาที

> **🎙️ พูด**: "และนี่คือ alert ที่ถูกสร้างขึ้น — count=6, severity=high, group key = src_ip + rule_name"

#### Step 3 — Drill down

# 🖱️ Click: คลิกปุ่ม > (Open detail)

> **🎙์ พูด**: "คลิกเข้าไปดู — เห็น raw logs ทั้ง 6 รายการที่ trigger + JSON metadata ครบ"

# 🖱️ Click: คลิกปุ่ม ✓ (Acknowledge)

> **🎙์ พูด**: "Operator acknowledge ได้ — PATCH endpoint ที่ audit log ไว้ — Viewer ทำได้เฉพาะ alert ของ tenant ตัวเอง RBAC enforced"

#### Step 4 — Webhook integration (bonus)

> **🎙์ พูด**: "Alert ส่ง webhook ได้ด้วย — มาดูกัน"

# 🖱️ Click: เปิด https://webhook.site → copy URL

# 🖱️ Click: Alert Rules → New rule → ตั้ง webhook_url → Save

```bash
# 💻 Terminal — trigger rule ใหม่:
for i in 1 2 3 4 5 6; do
  curl -sk -X POST https://localhost/api/v1/ingest \
    -H "Content-Type: application/json" \
    -d "{\"tenant\":\"demoA\",\"source\":\"api\",\"event_type\":\"malware_detected\",\"src_ip\":\"10.0.0.$i\"}" \
    > /dev/null
done
```

# 🖱️ Click: กลับ webhook.site → **เห็น payload ส่งมาเรียบร้อย!**

> **🎙️ พูด**: "Webhook payload ส่งมาทันที — มี alert ID, rule, severity, tenant ครบ — integrate กับ Slack, PagerDuty, email gateway ได้เลย"

---

### ⏱️ [22:00–25:00] Section 7 — RBAC + Multi-tenant Isolation

> **🎙️ พูด**: "ทีนี้มาดู RBAC — ระบบมี 2 role คือ Admin กับ Viewer และมี multi-tenant isolation"

# 🖱️ Click: Sign out (มุมขวาบน) → Login เป็น viewer / viewer123

> **🎙️ พูด**: "Login เป็น viewer ที่ผูกกับ tenant demoA — สังเกตว่าเมนู Users, Alert Rules หายไป — Viewer ไม่มีสิทธิ์จัดการ"

#### ทดสอบ 1 — Viewer เห็นเฉพาะ tenant ตัวเอง

```bash
# 💻 Terminal — ขอ viewer token:
VIEWER_TOKEN=$(curl -sk -X POST https://localhost/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"viewer","password":"viewer123"}' \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['access_token'])")

# ลอง bypass ไปดู demoB logs → ต้องได้ 0 row:
curl -sk -H "Authorization: Bearer $VIEWER_TOKEN" \
  "https://localhost/api/v1/logs?tenant=demoB&size=5" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Total logs visible to viewer (asking demoB): {d[\"total\"]}')
"
#    คาดหวัง: Total logs visible to viewer (asking demoB): 0
```

> **🎙️ พูด**: "แม้ Viewer จะพยายาม query `?tenant=demoB` — backend บังคับ scope จาก JWT claim ของ viewer — ได้ 0 row"

#### ทดสอบ 2 — Admin-only endpoint 403

```bash
# 💻 Terminal — Viewer ลองสร้าง alert rule ด้วย viewer → ต้องได้ 403:
curl -sk -o /dev/null -w "Status: %{http_code}\n" \
  -X POST https://localhost/api/v1/alerts \
  -H "Authorization: Bearer $VIEWER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"hack","event_types":["x"],"threshold":1,"window_minutes":1}'
#    คาดหวัง: Status: 403
```

> **🎙️ พูด**: "Admin-only endpoint คืน 403 — `require_admin` dependency ทำงาน — Viewer ไม่สามารถสร้าง rule หรือ user ใหม่ได้"

#### ทดสอบ 3 — Tenant selector ใน AlertRules (Admin)

# 🖱️ Click: Sign out → Login กลับเป็น admin → Alert Rules → New rule

> **🎙์ พูด**: "กลับมาเป็น Admin — เห็นตัวเลือก Tenant เพิ่มเข้ามา — สามารถเลือก 'All tenants (global)' หรือ scope เฉพาะ tenant ใด tenant หนึ่ง"

---

### ⏱️ [25:00–28:00] Section 8 — Security Deep Dive + Rate Limit

> **🎙️ พูด**: "Section นี้โชว์ security hardening ที่ระบบทำไว้ — สำคัญมากสำหรับ security product"

#### bcrypt + constant-time login

```bash
# 💻 Terminal — โชว์ bcrypt hash ใน DB:
docker compose exec -T postgres psql -U postgres -d logs \
  -c "SELECT username, role, substring(hashed_password from 1 for 25) || '...' AS hash_prefix FROM users;"
#    คาดหวัง: $2b$12$... (cost factor 12)
```

> **🎙️ พูด**: "Password เก็บเป็น bcrypt cost 12 — และที่สำคัญคือ login ใช้ **constant-time comparison** — ถ้า user ไม่มีในระบบก็ hash dummy password เพื่อให้ response time เท่ากัน ป้องกัน user enumeration"

#### Rate limit ที่ login (พร้อม live demo)

```bash
# 💻 Terminal — ทดสอบ rate limit (login ผิด 6 ครั้ง → 6th ต้องเป็น 429):
for i in 1 2 3 4 5 6; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST https://localhost/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"wrong"}')
  echo "Attempt $i: HTTP $STATUS"
done
#    คาดหวัง: 401 401 401 401 401 429
```

> **🎙️ พูด**: "Rate limit **5 attempts/minute/IP** — ตัวที่ 6 โดน 429 — ป้องกัน brute force password guessing"

#### TLS + Cert

```bash
# 💻 Terminal — ดู TLS cert:
echo | openssl s_client -connect localhost:443 -servername localhost 2>/dev/null \
  | openssl x509 -noout -subject -dates
#    คาดหวัง: subject=CN=localhost, valid 1 year
```

> **🎙️ พูด**: "TLS cert self-signed สำหรับ local dev — ใน production ใช้ cert-manager + Let's Encrypt ผ่าน Helm ingress"

---

### ⏱️ [28:00–30:00] Section 9 — Tests + IaC + Wrap-up

```bash
# 💻 Terminal — รัน test suite:
make test 2>&1 | tail -10
#    คาดหวัง: "91 passed"
```

> **🎙️ พูด**: "Test suite ครอบคลุม auth, search, alert, normalizer, retention, enrichment, schema drift — 91 ผ่านหมด"

```bash
# 💻 Terminal — โชว์ test ที่น่าสนใจ:
ls -la tests/test_*.py | awk '{printf "%-40s %s bytes\n", $NF, $5}'
```

> **🎙️ พูด**: "test_schema_drift.py เป็นตัวใหม่ — การันตีว่า init-db.sql ไม่หลุดจาก SQLAlchemy model — ป้องกันปัญหา migration ที่หลายคนเจอ"

```bash
# 💻 Terminal — โชว์ IaC:
echo "=== Helm chart ==="
find helm/ -type f -name "*.yaml" | grep -v "tests/" | head -15
echo "=== Terraform ==="
find terraform/ -type f -name "*.tf" 2>/dev/null | head -10
```

> **🎙️ พูด**: "Helm chart มี deployment, service, configmap, secret, hpa, ingress ครบ — Terraform มี EKS, VPC, RDS modules — deploy ขึ้น AWS ได้ใน 1 คำสั่ง"

# 📺 Cut → summary slide

#### สรุปคะแนน

| หมวด | คะแนน | สถานะ |
|---|---|---|
| สถาปัตยกรรม & เอกสาร | 15 | ✅ docs/ ครบ 3 ไฟล์ |
| Ingestion | 20 | ✅ 4+ sources ทำงานจริง |
| Normalization/Schema | 10 | ✅ ตาม spec §3 ทุก field |
| Storage & Query | 10 | ✅ Postgres + JSONB + indexes |
| Dashboard/UI | 10 | ✅ 5 หน้าตาม spec §7 |
| Alerting | 10 | ✅ Brute-Force 5/5min ทำงานจริง |
| Security | 10 | ✅ JWT+RBAC+HTTPS+rate limit+bcrypt |
| Deployment | 10 | ✅ Appliance + SaaS + Helm + Terraform |
| Tests & DX | 5 | ✅ 91 tests + Postman + samples |
| **รวม** | **100** | ✅ |

> **🎙️ พูด** (จบแบบมั่นใจ): "จุดแข็งที่อยากเน้น — **race-safe alert engine** ด้วย FOR UPDATE locking, **JWT re-validation** ป้องกัน privilege escalation หลัง demote, **constant-time login** ป้องกัน user enumeration, **HTTPS + HSTS + HttpOnly cookie + rate limit** ครบชุด"

> **🎙️ พูด**: "ขอบคุณครับ — พร้อมรับคำถาม"

# 📺 Cut → end card

---

## 🎯 คำถามที่กรรมการอาจถาม + คำตอบเตรียมไว้

### Q1: ถ้า stack ตก + restart ตรงกลาง ingest จะเกิดอะไร?
> **🎙️ ตอบ**: "ทุก insert อยู่ใน transaction + commit ทันที — log ที่ commit แล้วยังอยู่ ส่วนที่ยังไม่ commit หาย — alert ที่ fire แล้วส่ง webhook ไม่สำเร็จมี retry ตอน startup (`_retry_pending_deliveries`)"

### Q2: ทำไมไม่ใช้ Elasticsearch/OpenSearch แทน Postgres?
> **🎙️ ตอบ**: "Postgres + JSONB + GIN index ตอบโจทย์ demo scale + ลด dependency ให้ Appliance mode spin up ได้บนเครื่องเดียว — architecture ออกแบบให้สลับ storage backend ได้ถ้า scale เกิน"

### Q3: RBAC ป้องกัน SQL injection ใน search query ได้ยังไง?
> **🎙️ ตอบ**: "ใช้ SQLAlchemy ORM parameter binding ทุกที่ + มี `_escape_like()` function กับ `%` `_` `\` ก่อน LIKE query — และ input validation ทุก field ผ่าน Pydantic schema"

### Q4: Multi-tenant isolation ใช้ row-level หรือ schema-per-tenant?
> **🎙️ ตอบ**: "Row-level — ทุก row มี `tenant` column — `get_current_user` ใส่ filter อัตโนมัติ — Viewer JWT claim override query param — test_rbac_viewer_tenant_isolation ทดสอบเคส bypass"

### Q5: Helm chart ทำงานจริงไหม?
> **🎙️ ตอบ**: "ใช่ครับ — chart มี deployment, service, configmap, secret, hpa, ingress — deploy ได้ด้วย `helm install log-mgmt helm/log-management --set backend.env.SECRET_KEY=...` — หรือใช้ Terraform เรียก Helm provider"

### Q6: มี rate limit ที่ API อื่นนอกจาก login ไหม?
> **🎙️ ตอบ**: "Nginx มี `limit_req_zone` ที่ /api/ (100r/m) และ /api/v1/auth/login (10r/m) — backend ใช้ slowapi เพิ่มเติมที่ 5/minute สำหรับ /auth/login (per-IP) — **defense in depth**"

### Q7: จะ scale เป็น 10K logs/second ได้ไหม?
> **🎙️ ตอบ**: "ปัจจุบันทดสอบที่ ~500 logs/s บนเครื่องเดียว — ถ้ามากกว่านั้นใช้ Kafka + Vector/Fluent Bit collector แทน direct POST — backend เขียน async ไว้รับได้"

### Q8: (ถ้าถามเรื่อง 422/401/429) ทำไม Postman ส่งแล้วได้ error แบบนี้?
> **🎙️ ตอบ**: "422 = Pydantic validation — body ไม่ตรง schema — เช็ค Content-Type + field names — 401 = ไม่ได้ login หรือ cookie หมดอายุ — 429 = rate limit — ทุก error มี HTTP code standard ตาม RFC"

---

## 🆘 Live Troubleshooting — ถ้าพังระหว่างอัด

### ถ้า stack ตายกลางคลิป
```bash
# 💻 — พูด: "ขอ recover สักครั้งนะครับ"
docker compose ps           # ดูว่าตัวไหนตาย
docker compose restart <service>
# ถ้า Nginx ตาย: รอ 5 วินาที + ทดสอบ health
curl -sk https://localhost/health
# ตัดช่วงนี้ออกในการ edit
```

### ถ้า login ค้าง / ไม่ผ่าน
```bash
# 💻 — พูด: "ขอตรวจ session ครับ"
# 1. ดู cookie ใน DevTools
# 2. ลอง logout + login ใหม่
# 3. ถ้ายังไม่ได้ → restart backend
docker compose restart backend && sleep 5
```

### ถ้า alert ไม่ขึ้น
```bash
# 💻 — พูด: "ลองตรวจ alert pipeline ครับ"
# 1. ดู alert_rules table
docker compose exec -T postgres psql -U postgres -d logs \
  -c "SELECT id, name, threshold, window_minutes, enabled FROM alert_rules;"
# 2. ถ้า 0 row → restart backend เพื่อ re-seed
docker compose restart backend && sleep 5
# 3. ตรวจ triggered_alerts
docker compose exec -T postgres psql -U postgres -d logs \
  -c "SELECT id, rule_name, count, triggered_at FROM triggered_alerts ORDER BY id DESC LIMIT 3;"
```

### ถ้า rate limit ติดค้าง
```bash
# 💻 — พูด: "rate limit จะ reset ภายใน 1 นาทีครับ"
# รอ หรือ
docker compose restart backend    # reset in-memory counter
```

### ถ้า syslog ไม่เข้า
```bash
# 💻 — พูด: "ขอเช็ค Nginx stream block"
docker compose exec nginx cat /etc/nginx/nginx.conf | grep -A 5 "stream"
# ดูว่า backend container ยัง resolve DNS ได้
docker compose exec nginx nslookup backend
```

### ถ้าจะเริ่มใหม่ตั้งแต่ต้น
```bash
# 💻 — พูด: "ขอ reset ให้สะอาดครับ"
docker compose exec -T postgres psql -U postgres -d logs \
  -c "TRUNCATE logs, triggered_alerts RESTART IDENTITY;"
docker compose restart backend
sleep 5
# ทดสอบ 1 ingest ก่อนดำเนินการต่อ
curl -sk -X POST https://localhost/api/v1/ingest \
  -H "Content-Type: application/json" \
  -d '{"tenant":"demoA","source":"api","event_type":"smoke_test"}'
```

---

## 📋 Pre-recording Checklist (ทำก่อนกด Record)

### Stack
- [ ] `docker compose ps` — 5/5 Up + healthy
- [ ] `make test` — 91/91 passed
- [ ] DB truncate + backend restart (เพื่อ re-seed rule)
- [ ] TLS cert ยังไม่หมดอายุ (`openssl s_client ... | openssl x509 -dates`)
- [ ] curl ingest test ผ่าน 200

### Postman
- [ ] Import `api_collection.json` (schema v2.1)
- [ ] Environment "Log Management Local" + baseUrl = `https://localhost`
- [ ] SSL verification = OFF
- [ ] Auth → Login → Send → token ถูก save อัตโนมัติ

### Browser
- [ ] Chrome tabs: Frontend (`https://localhost/`) + Swagger (`http://localhost:8000/docs`)
- [ ] Webhook.site URL copy แล้ว (สำหรับ webhook demo)
- [ ] Hard reload ล่าสุด (Cmd+Shift+R)

### Equipment
- [ ] Headset mic + Krisp/RTX Voice (noise suppression)
- [ ] Recording software: OBS Studio / Loom
- [ ] Resolution 1920×1080, 30 fps
- [ ] Webcam overlay ติด (optional)

### Mindset
- [ ] อ่าน TL;DR + Section ที่จะอัด 1 รอบก่อน
- [ ] มีน้ำ/กาแฟข้างๆ
- [ ] ปิด notification ทุกชนิด

---

## 🎨 Optional Enhancements ที่เพิ่มคะแนน (ถ้าเวลาเหลือ)

1. **Live tenant create** — `POST /tenants` สร้าง tenant ใหม่ + โชว์ใน dropdown ของ AlertRules
2. **HTTPS redirect demo** — `curl http://localhost/` → 301 → `https://localhost/`
3. **Hot reload demo** — แก้ alert rule → restart → เห็น effect ทันที
4. **Webhook retry demo** — ปิด internet → trigger alert → เปิด internet → restart → เห็น retry สำเร็จ
5. **System log dashboard** — Grafana + Prometheus metrics ของ backend
6. **Schema drift test live** — รัน `pytest tests/test_schema_drift.py -v` โชว์ว่าการันตี model ↔ SQL ตรงกัน

---

## 📂 Related Files

- `spec.md` — ข้อกำหนดฉบับเต็ม
- `docs/architecture.md` — สถาปัตยกรรม + data flow
- `docs/setup_appliance.md` — ขั้นตอน deploy Appliance
- `docs/setup_saas.md` — ขั้นตอน deploy SaaS
- `api_collection.json` — Postman collection (schema v2.1, raw JSON bodies)
- `samples/post_logs.py` — ingest 6 sources ผ่าน HTTP
- `samples/send_syslog.sh` — ยิง syslog 7 บรรทัดผ่าน UDP
- `_internal/CODE_REVIEW.md` — บันทึก bug + fix
- `_internal/SPEC_COMPLIANCE_REVIEW.md` — spec compliance report
- `_internal/ACTION_PLAN.md` — แผนงาน
- `_internal/RUN.md` — วิธีรันโปรเจกต์

---

> **💡 Tip หลังอัดเสร็จ**: ถ้าอยากให้ช่วย review คลิป หรือแนะนำจุดที่ควรตัด/เร่ง บอกได้เลยครับ — แนะนำให้ edit ลด 5% ของความยาวรวม เพราะพูดสดมักจะยาวเกิน