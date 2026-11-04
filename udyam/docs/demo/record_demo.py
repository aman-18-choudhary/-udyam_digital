"""Records the product demo video by driving Google Chrome with Playwright.

It records only the page (not the screen), so nothing else on the machine can appear in the video.
Two segments are recorded and joined by make_video.sh:
  1. the live site's sign-in page (nothing is typed there; no account is used)
  2. the full journey on an isolated local copy: no Clerk, Supabase or Razorpay, sample applicants on,
     and a fresh SQLite database. See README "Record the demo video".

    python record_demo.py LOCAL_URL OUT_DIR GSTIN
"""
import json
import re
import sys
import time

from playwright.sync_api import sync_playwright

LOCAL, OUT, GSTIN = sys.argv[1], sys.argv[2], sys.argv[3]
LIVE = "https://udyam-digital.onrender.com"
W, H = 1280, 720

OVERLAY = r"""
(() => {
  const css = `
  #__ov * { box-sizing: border-box; }
  #__cap { position: fixed; left: 50%; bottom: 26px; transform: translate(-50%, 16px); max-width: 86vw; padding: 12px 24px; border-radius: 999px;
    background: rgba(10,8,15,.9); border: 1px solid rgba(255,90,120,.65); color: #fff; font: 600 21px/1.3 system-ui, sans-serif; letter-spacing: .01em;
    box-shadow: 0 10px 40px rgba(255,31,69,.35); opacity: 0; transition: opacity .35s, transform .35s; z-index: 2147483646; pointer-events: none; text-align: center; }
  #__cap.on { opacity: 1; transform: translate(-50%, 0); }
  #__card { position: fixed; inset: 0; display: grid; place-content: center; text-align: center; gap: 14px; opacity: 0; pointer-events: none; transition: opacity .5s;
    background: radial-gradient(80% 70% at 50% 45%, rgba(120,0,25,.78), rgba(7,6,11,.94)); color: #fff; font-family: system-ui, sans-serif; z-index: 2147483645; }
  #__card.on { opacity: 1; }
  #__card b { font-size: 58px; letter-spacing: -.02em; text-shadow: 0 0 40px rgba(255,31,69,.7); }
  #__card span { font-size: 25px; color: #ffb3c0; } #__card i { font-size: 19px; color: #ddd; font-style: normal; }
  #__cur { position: fixed; left: 0; top: 0; width: 28px; height: 28px; margin: -14px 0 0 -14px; border-radius: 50%; border: 3px solid #ff1f45; background: rgba(255,31,69,.18);
    box-shadow: 0 0 18px rgba(255,31,69,.8); pointer-events: none; z-index: 2147483647; opacity: 0; transition: opacity .2s; }
  .__rip { position: fixed; width: 20px; height: 20px; margin: -10px 0 0 -10px; border-radius: 50%; border: 3px solid #fff; pointer-events: none; z-index: 2147483647; animation: __r .6s ease-out forwards; }
  @keyframes __r { to { transform: scale(4); opacity: 0; } }`;
  const ensure = () => {
    if (document.getElementById('__ov')) return;
    const r = document.createElement('div'); r.id = '__ov';
    r.innerHTML = `<style>${css}</style><div id="__cap"></div><div id="__card"><b></b><span></span><i></i></div><div id="__cur"></div>`;
    document.documentElement.appendChild(r);
  };
  window.__cap = (t) => { ensure(); const c = document.getElementById('__cap'); if (t) c.textContent = t; c.classList.toggle('on', !!t); };
  window.__card = (a, b, c) => { ensure(); const k = document.getElementById('__card');
    if (!a) { k.classList.remove('on'); return; }
    k.querySelector('b').textContent = a; k.querySelector('span').textContent = b || ''; k.querySelector('i').textContent = c || ''; k.classList.add('on'); };
  window.addEventListener('mousemove', (e) => { ensure(); const c = document.getElementById('__cur'); c.style.transform = `translate(${e.clientX}px,${e.clientY}px)`; c.style.opacity = 1; }, true);
  window.addEventListener('mousedown', (e) => { ensure(); const d = document.createElement('div'); d.className = '__rip'; d.style.left = e.clientX + 'px'; d.style.top = e.clientY + 'px'; document.documentElement.appendChild(d); setTimeout(() => d.remove(), 700); }, true);
})();
"""

markers = {}
t0 = 0.0


def mark(name):
    markers[name] = round(time.time() - t0, 1)
    print(f"[{markers[name]:6.1f}s] {name}", flush=True)


def cap(page, text):
    page.evaluate("t => window.__cap(t)", text)


def card(page, a=None, b="", c=""):
    page.evaluate("([a, b, c]) => window.__card(a, b, c)", [a, b, c])


PACE = 0.6   # reading pauses are scaled to keep the whole video near three minutes


def pause(page, s):
    page.wait_for_timeout(int(s * 1000 * (PACE if s >= 1.5 else 0.85)))


def click(page, loc, settle=0.35):
    loc.scroll_into_view_if_needed()
    box = loc.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=22)
    pause(page, settle)
    loc.click()


def type_in(page, loc, text, delay=42):
    click(page, loc)
    page.keyboard.type(text, delay=delay)
    pause(page, 0.4)
    page.keyboard.press("Enter")


def bot_count(page):
    return page.locator(".bubble.bot:not(.typing)").count()


def wait_reply(page, before, timeout=45000):
    page.wait_for_function(
        "n => document.querySelectorAll('.bubble.bot:not(.typing)').length > n && !document.querySelector('.bubble.typing')",
        arg=before, timeout=timeout)
    pause(page, 0.7)


def new_page(p, url, video_dir):
    browser = p.chromium.launch(channel="chrome", headless=True,
                                args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--hide-scrollbars"])
    ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=video_dir,
                              record_video_size={"width": W, "height": H}, locale="en-IN", color_scheme="dark")
    ctx.add_init_script(OVERLAY)
    page = ctx.new_page()
    page.set_default_timeout(40000)
    return browser, ctx, page


def segment_live(p):
    global t0
    browser, ctx, page = new_page(p, LIVE, OUT + "/live")
    t0 = time.time()
    page.goto(LIVE, wait_until="domcontentloaded")
    page.wait_for_selector("text=Sign in", timeout=90000)
    pause(page, 2.5)
    mark("live_landing")
    card(page, "Project Udyam Digital", "Airtel Sync 2026 · Team Cracker", "Get your business online in one sitting")
    pause(page, 4.2)
    card(page)
    cap(page, "Live now at udyam-digital.onrender.com: sign-in by Clerk")
    page.mouse.move(900, 330, steps=30)
    pause(page, 5)
    cap(page, "")
    ctx.close()
    browser.close()
    json.dump(markers, open(OUT + "/markers_live.json", "w"))


def segment_local(p):
    global t0
    markers.clear()
    browser, ctx, page = new_page(p, LOCAL, OUT + "/local")
    t0 = time.time()
    page.goto(LOCAL, wait_until="domcontentloaded")
    page.wait_for_selector(".bubble.bot")
    pause(page, 2)

    # 1. advisor
    mark("advisor")
    cap(page, "1  The advisor asks a few plain-language questions")
    pause(page, 2.5)
    n = bot_count(page)
    click(page, page.get_by_role("button", name="Clinic", exact=True)); wait_reply(page, n)
    n = bot_count(page)
    type_in(page, page.get_by_label("Your answer"), "5"); wait_reply(page, n)
    n = bot_count(page)
    type_in(page, page.get_by_label("Your answer"), "Nagpur"); wait_reply(page, n)
    n = bot_count(page)
    click(page, page.get_by_role("button", name="Business broadband", exact=True)); wait_reply(page, n)
    cap(page, "The GSTIN is checked against the registry, instantly")
    n = bot_count(page)
    type_in(page, page.get_by_label("Your answer"), GSTIN, delay=28); wait_reply(page, n)
    page.wait_for_selector("text=Your bundle")
    mark("recommendation")
    cap(page, "A bundle with one clear monthly price, explained in plain words")
    pause(page, 6)
    cap(page, "Rules decide eligibility and price, never the AI: Biz Fibre 1G is not sold in a Tier 2 city")
    n = bot_count(page)
    type_in(page, page.get_by_label("Your answer"), "I want Biz Fibre 1G", delay=40); wait_reply(page, n)
    mark("rule_refusal")
    pause(page, 5)
    click(page, page.get_by_role("button", name="Looks good, continue", exact=True))

    # 2. quote
    page.wait_for_selector("text=Build your bundle")
    mark("quote")
    cap(page, "2  Toggle add-ons and the price updates live")
    pause(page, 2.5)
    click(page, page.locator("li", has_text="Cloud CCTV").get_by_role("checkbox"))
    pause(page, 2)
    click(page, page.get_by_role("button", name="24 months"))
    pause(page, 2.5)
    cap(page, "Dependencies are enforced: a backup link needs an internet link")
    click(page, page.locator(".lines li").first.get_by_role("checkbox"))  # the internet link is the first row
    page.wait_for_selector("li.bad")
    mark("dependency")
    pause(page, 4)
    click(page, page.locator(".lines li").first.get_by_role("checkbox"))  # the internet link is the first row
    pause(page, 1.5)
    click(page, page.get_by_role("button", name="Verify documents"))

    # 3. kyc
    page.wait_for_selector("text=Your documents, your choice")
    mark("consent")
    cap(page, "3  Smart KYC starts with a clear consent notice (DPDP Act)")
    pause(page, 3)
    page.mouse.wheel(0, 380)
    pause(page, 2.5)
    click(page, page.locator("label.agree input[type=checkbox]"))
    pause(page, 1)
    click(page, page.get_by_role("button", name="Agree and continue"))
    page.wait_for_selector("text=Verify your business")
    cap(page, "A stale electricity bill is caught (sample applicant K11)")
    pause(page, 2)
    sel = page.get_by_label("Load a sample applicant")
    click(page, sel)
    sel.select_option("K11")
    page.wait_for_function("document.querySelectorAll('.slot.ok, .slot.warn').length >= 4", timeout=60000)
    pause(page, 1.5)
    click(page, page.get_by_role("button", name="Verify documents", exact=True))
    page.wait_for_selector(".banner")
    mark("kyc_fail")
    pause(page, 2)
    # the failing check sits below the fold of the result list: scroll it into view for the viewer
    page.locator(".checks").evaluate("el => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })")
    pause(page, 4)
    cap(page, "A clean applicant (K03) verifies in seconds")
    click(page, sel)
    sel.select_option("K03")
    pause(page, 1)
    page.wait_for_function("document.querySelectorAll('.slot.ok, .slot.warn').length >= 4", timeout=60000)
    pause(page, 1.5)
    click(page, page.get_by_role("button", name="Verify documents", exact=True))
    page.wait_for_selector(".banner.verified, .banner.review")
    mark("kyc_ok")
    pause(page, 2)
    page.locator(".checks").evaluate("el => el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })")
    pause(page, 2.5)
    click(page, page.get_by_role("button", name="Continue to payment"))

    # 4. pay
    page.wait_for_selector("text=Review and pay")
    mark("pay")
    cap(page, "4  Payments: a declined attempt is handled and can be retried")
    pause(page, 2.5)
    click(page, page.locator("label.tick", has_text="Simulate a bank decline").locator("input"))
    click(page, page.get_by_role("button", name=re.compile(r"^Pay ₹")))
    page.wait_for_selector("text=declined")
    pause(page, 3)
    cap(page, "Retry succeeds")
    click(page, page.get_by_role("button", name=re.compile(r"^Pay ₹")))

    # 5. tracker
    page.wait_for_selector("text=Tracking your order")
    mark("tracker")
    cap(page, "5  Live order tracking: no chasing calls")
    page.wait_for_selector("text=You are live!", timeout=60000)
    mark("live")
    pause(page, 4)

    # my orders
    click(page, page.get_by_role("button", name=re.compile(r"My orders")))
    page.wait_for_selector("text=Everything you have ordered")
    mark("my_orders")
    cap(page, "Customers can find and track every order any time")
    pause(page, 4.5)

    # 6. console
    click(page, page.get_by_role("link", name="Staff console"))
    page.wait_for_selector("text=Leads the digital journey did not close")
    mark("console")
    cap(page, "6  Sales console: leads the digital journey missed, ranked, with a next action")
    pause(page, 5.5)
    click(page, page.get_by_role("tab", name=re.compile("Orders")))
    cap(page, "Ops advance orders and approve manual KYC reviews")
    pause(page, 4)
    click(page, page.get_by_role("tab", name="Funnel"))
    cap(page, "The funnel the case study starts from: 5,000 leads, 368 activated")
    page.wait_for_selector(".bar")
    mark("funnel")
    pause(page, 5)

    cap(page, "")
    card(page, "Project Udyam Digital", "Live: udyam-digital.onrender.com", "Code: github.com/aman-18-choudhary/-udyam_digital")
    pause(page, 5.5)
    ctx.close()
    browser.close()
    json.dump(markers, open(OUT + "/markers_local.json", "w"))


with sync_playwright() as p:
    which = sys.argv[4] if len(sys.argv) > 4 else "both"
    if which in ("both", "live"):
        segment_live(p)
    if which in ("both", "local"):
        segment_local(p)
print("done")
