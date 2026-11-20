# C2 — Insta-Lid CRM (Multi-Tenant B2B SaaS)

Bitta GitHub repozitoriy va bitta Render.com servisi ichida **50+ biznesni** alohida boshqaruvchi Instagram Comment-to-DM va Kafolatlangan Lid yig'ish tizimi.

## Fayllar Tuzilmasi
- `main.py` — FastAPI server, Meta Webhook (`/webhook`), Health Check (`/health`) va Click/Payme Auto-Billing (`/api/payment/webhook`).
- `bot.py` — Multi-Tenant Telegram boshqaruv boti (`aiogram 3.x`), Onboarding, Reels ulash, Skript shablonlari, Tariflar va Admin 1-bosishda tasdiqlash.
- `queue_worker.py` — Har bir Instagram biznes sahifasi uchun alohida 10 soniyali Anti-Ban navbat (`Per-Tenant asyncio.Queue`).
- `funnel_engine.py` — Direct suhbat voronkasi (Ism -> `+998` Tel validatsiya -> Miqdor), Bonus lidlar (`+15/+30/+50/+100`), Avtomatik Stop va Zaxira Baza dvigateli.
- `sheets_manager.py` — `urozaliyevyahyobek@gmail.com` Service Account orqali mijozga **View-Only Asosiy CRM** va yashirin **Private Zaxira Baza** jadvallarini yaratish hamda ko'chirish.
- `instagram_api.py` — Meta Instagram Graph API v21.0 asinxron mijoz (`httpx`).
- `database.py` — SQLAlchemy 2.0 Async ORM (Render/Neon PostgreSQL + lokal SQLite).
- `config.py` — Barcha tariflar (`C+P` va `C+P+L`), bonuslar va 4 ta tayyor sotuv shabloni.

## 5 Daqiqada Deploy Qilish (Render.com)
1. Papkadagi `env.example` ni `.env` ga, `gitignore.txt` ni `.gitignore` ga o'zgartiring.
2. Yangi GitHub repozitoriyga yuklang:
   ```bash
   git init
   git add .
   git commit -m "Initial C2 Insta-Lid CRM SaaS"
   git branch -M main
   git remote add origin https://github.com/<USERNAME>/c2-insta-lid-saas.git
   git push -u origin main
   ```
3. **Neon.tech** yoki **Supabase** da bepul PostgreSQL baza ochib `DATABASE_URL` linkini oling.
4. **Google Cloud Console** (`urozaliyevyahyobek@gmail.com`) da **Google Sheets API** va **Google Drive API** ni yoqib, Service Account JSON kalitini oling.
5. **Render.com** -> New Web Service -> GitHub reponi ulang (`render.yaml` Python 3.11.11 va start komandasini avtomatik sozlaydi).
6. Render **Environment Variables** ga `BOT_TOKEN`, `ADMIN_TG_ID`, `DATABASE_URL`, `GOOGLE_CREDENTIALS_JSON`, `PAYMENT_CARD_NUMBER` ni kiriting.
7. **Meta Developer Portal** -> Webhooks -> Callback URL: `https://<sizning-render-url>/webhook`, Verify Token: `c2_insta_lid_verify_2026`, `comments` va `messages` ni yoqing.
8. **cron-job.org** da har 5 daqiqada `https://<sizning-render-url>/health` ga ping qo'ying.
