from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
import wave
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import imageio_ffmpeg
import mss
import numpy as np
import requests
import soundcard as sc
import yaml
from faster_whisper import WhisperModel
from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeoutError

import session_events as ev

MEDIA_EXTS = (".mp4", ".m4v", ".mov", ".webm", ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac")
STREAM_EXTS = (".m3u8", ".mpd")
LESSON_HINTS = ("lesson", "lekcja", "module", "modul", "chapter", "training", "video", "course", "kurs", "material", "topic", "session", "webinar", "recording")

LOGIN_TIMEOUT_SECONDS = 600


def log(msg=""):
    print(msg, flush=True)


def emit(event, **fields):
    """Wypisz zdarzenie statusu, które GUI potrafi odczytać i pokazać."""
    print(ev.format_event(event, **fields), flush=True)


def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cfg.setdefault("portal_name", urlparse(cfg.get("start_url", "")).netloc or "Portal")
    cfg.setdefault("output_dir", str(Path.home()/"Documents"/"CourseArchiver"))
    cfg.setdefault("browser_profile_dir", str(Path.home()/".course_archiver_browser"))
    cfg.setdefault("lesson_url_regex", "")
    cfg.setdefault("link_selector", "")
    cfg.setdefault("max_lessons", 500)
    cfg.setdefault("crawl_depth", 3)
    cfg.setdefault("capture_seconds", 8)
    cfg.setdefault("download_media", True)
    cfg.setdefault("record_fallback", True)
    cfg.setdefault("record_fps", 10)
    cfg.setdefault("record_max_minutes", 180)
    cfg.setdefault("transcribe", True)
    cfg.setdefault("whisper_model", "large-v3")
    cfg.setdefault("whisper_language", "pl")
    cfg.setdefault("same_origin_only", True)
    cfg.setdefault("debug", False)
    cfg.setdefault("record_monitor", {"index": 1})
    cfg.setdefault("browser_on_record_monitor", True)
    cfg.setdefault("record_audio_device", "__default__")
    cfg.setdefault("session_state_file", str(default_session_state_file(cfg["portal_name"])))
    return cfg


def default_session_state_file(portal_name: str) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (portal_name or "portal").strip()).strip("_") or "portal"
    return ev.session_marker_path(Path.home() / ".course_archiver_app", slug)


def safe_name(value: str, limit=120):
    value = unicodedata.normalize("NFKC", value or "").strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .") or "bez_nazwy"
    if len(value)>limit:
        value = value[:limit-10].rstrip()+"_"+hashlib.sha1(value.encode()).hexdigest()[:8]
    return value


def canonical(url):
    p=urlparse(url); return p._replace(fragment="").geturl()


def same_origin(a,b):
    pa,pb=urlparse(a),urlparse(b); return (pa.scheme,pa.netloc)==(pb.scheme,pb.netloc)


def stable_id(url):
    return hashlib.sha1(canonical(url).encode()).hexdigest()[:12]


@dataclass
class Lesson:
    url: str
    lesson_id: str
    title: str
    category: str
    order: int=0
    media_url: Optional[str]=None
    media_file: Optional[str]=None
    transcript_txt: Optional[str]=None
    transcript_md: Optional[str]=None
    status: str="discovered"
    note: Optional[str]=None


class State:
    def __init__(self,path):
        self.path=path; self.data={"lessons":{},"updated_at":None}
        if path.exists():
            try:self.data=json.loads(path.read_text(encoding="utf-8"))
            except Exception:pass
    def get(self,lid):return self.data.get("lessons",{}).get(lid,{})
    def put(self,l):
        self.data.setdefault("lessons",{})[l.lesson_id]=asdict(l); self.data["updated_at"]=time.strftime("%Y-%m-%d %H:%M:%S")
        self.path.write_text(json.dumps(self.data,ensure_ascii=False,indent=2),encoding="utf-8")


def looks_like_login(page:Page):
    try:
        if page.locator('input[type="password"]').count()>0:return True
        u=page.url.lower(); return any(x in u for x in ("/login","/signin","/sign-in","/auth")) and page.locator("form").count()>0
    except Exception:return False


def manual_login(page:Page,start_url)->bool:
    """Doprowadź stronę do stanu zalogowania.

    Zwraca True, jeżeli sesja była już aktywna (nie trzeba było się logować),
    False, jeżeli użytkownik zalogował się w trakcie tego uruchomienia.
    Brak logowania w wyznaczonym czasie kończy się wyjątkiem.
    """
    if not looks_like_login(page):
        log("\n=== SESJA ===")
        log("Sesja zapisana lokalnie jest nadal aktywna — logowanie nie jest wymagane.")
        return True
    log("\n=== LOGOWANIE ===")
    log("Zaloguj się ręcznie w otwartym oknie Chrome. Obsługiwane są MFA/CAPTCHA.")
    log("Aplikacja automatycznie rozpozna zakończenie logowania (maks. 10 minut).")
    emit(ev.EVENT_LOGIN_REQUIRED, url=page.url)
    deadline=time.time()+LOGIN_TIMEOUT_SECONDS
    stable_since=None
    while time.time()<deadline:
        page.wait_for_timeout(1000)
        logged=not looks_like_login(page)
        if logged:
            if stable_since is None: stable_since=time.time()
            if time.time()-stable_since>=2.0:
                page.goto(start_url,wait_until="domcontentloaded",timeout=90000);page.wait_for_timeout(1000)
                if not looks_like_login(page):
                    log("Logowanie zakończone; sesja została zachowana lokalnie.")
                    return False
                stable_since=None
        else:
            stable_since=None
    raise RuntimeError("Nie wykryto zakończenia logowania w ciągu 10 minut.")


def verify_session(page:Page,start_url)->bool:
    """Potwierdź na stronie startowej, że sesja naprawdę działa."""
    try:
        if canonical(page.url)==canonical(start_url) and not looks_like_login(page):
            return True
    except Exception:pass
    try:
        page.goto(start_url,wait_until="domcontentloaded",timeout=90000);page.wait_for_timeout(700)
    except Exception as e:
        log(f"[WARN] Nie udało się ponownie otworzyć strony startowej: {e}")
        return not looks_like_login(page)
    return not looks_like_login(page)


def login_stage(page:Page,cfg)->bool:
    """Pełny etap logowania: doprowadź do sesji, potwierdź ją i zapisz znacznik.

    To jest miejsce, w którym kończył się tryb --login-only w wersji 4.5 bez
    żadnej informacji zwrotnej dla GUI. Teraz zawsze powstaje jednoznaczny
    komunikat oraz trwały znacznik stanu sesji.
    """
    start_url=cfg["start_url"]
    already=manual_login(page,start_url)
    if not verify_session(page,start_url):
        raise RuntimeError("Po zalogowaniu portal nadal pokazuje formularz logowania. Sesja nie została potwierdzona.")
    marker=Path(os.path.expandvars(str(cfg.get("session_state_file") or default_session_state_file(cfg["portal_name"])))).expanduser()
    try:
        ev.write_session_marker(marker,portal_name=cfg.get("portal_name"),start_url=start_url,
                                browser_profile_dir=str(cfg.get("browser_profile_dir") or ""),
                                already_logged_in=bool(already))
    except Exception as e:
        log(f"[WARN] Nie udało się zapisać znacznika sesji: {e}")
    log("Status: ZALOGOWANO. Sesja przeglądarki jest zapisana w lokalnym profilu.")
    emit(ev.EVENT_LOGIN_OK,already_logged_in=bool(already),url=page.url,
         portal_name=cfg.get("portal_name"),session_file=str(marker))
    return already


def expand_ui(page:Page):
    try: page.evaluate("() => document.querySelectorAll('details:not([open])').forEach(x=>x.open=true)")
    except Exception: pass
    for sel in ["nav [aria-expanded='false']","aside [aria-expanded='false']","[class*='sidebar'] [aria-expanded='false']","[class*='course'] [aria-expanded='false']","[class*='module'] [aria-expanded='false']"]:
        try:
            loc=page.locator(sel)
            for i in range(min(loc.count(),60)):
                try:loc.nth(i).click(timeout=500);page.wait_for_timeout(40)
                except Exception:pass
        except Exception:pass


def extract_title(page:Page,fallback):
    for sel in ["h1","main h2","article h2","[class*='lesson'][class*='title']","[class*='title'][class*='lesson']","[class*='video'][class*='title']"]:
        try:
            loc=page.locator(sel).first
            if loc.count():
                t=loc.inner_text(timeout=800).strip()
                if 1<len(t)<260:return t
        except Exception:pass
    try:return page.title().strip() or fallback
    except Exception:return fallback


def extract_category(page:Page,current):
    for sel in ["nav[aria-label*='breadcrumb' i] li",".breadcrumb li",".breadcrumbs li","[class*='breadcrumb'] a"]:
        try:
            vals=[x.strip() for x in page.locator(sel).all_inner_texts() if x.strip()]
            if len(vals)>=2:return vals[-2][:160]
        except Exception:pass
    try:
        val=page.evaluate("""(current)=>{const clean=u=>(u||'').split('#')[0].replace(/\\/$/,''); const a=[...document.querySelectorAll('a[href]')].find(x=>clean(x.href)===clean(current)); if(!a)return null; let n=a; for(let i=0;i<6&&n;i++,n=n.parentElement){const p=n.parentElement;if(!p)continue;const h=p.querySelector(':scope > h1,:scope > h2,:scope > h3,:scope > h4,:scope > strong,:scope > [class*=title]');if(h&&h.innerText.trim().length<160)return h.innerText.trim();} return null;}""",current)
        if val:return str(val)
    except Exception:pass
    return "Bez kategorii"


def link_candidates(page:Page,cfg):
    expand_ui(page)
    selector=cfg.get("link_selector") or "a[href]"
    try:
        raw=page.eval_on_selector_all(selector,"els => els.map(a => ({href:a.href||a.getAttribute('href'), text:(a.innerText||a.textContent||'').trim(), cls:a.className||'', aria:a.getAttribute('aria-label')||''})).filter(x=>x.href)")
    except Exception:
        raw=page.eval_on_selector_all("a[href]","els => els.map(a => ({href:a.href, text:(a.innerText||'').trim(), cls:a.className||'', aria:a.getAttribute('aria-label')||''}))")
    return raw


def lesson_score(item,cfg,start_url):
    url=canonical(urljoin(start_url,item.get("href") or "")); text=" ".join(str(item.get(k) or "") for k in ("text","cls","aria")).lower(); low=url.lower()
    if not url.startswith(("http://","https://")):return -999
    if cfg.get("same_origin_only",True) and not same_origin(url,start_url):return -999
    rgx=cfg.get("lesson_url_regex","").strip()
    if rgx:
        try:return 100 if re.search(rgx,url,re.I) else -999
        except re.error:return -999
    score=0
    for h in LESSON_HINTS:
        if h in low:score+=4
        if h in text:score+=3
    if re.search(r"/\d{2,}([/?#]|$)",low):score+=2
    if any(x in low for x in ("logout","privacy","policy","terms","account","profile","cart","checkout")):score-=10
    return score


def discover_lessons(page:Page,cfg,out_dir:Path):
    start=canonical(cfg["start_url"]); queue=[(start,0)]; seen=set(); found={}; maxn=int(cfg["max_lessons"]); depthmax=int(cfg.get("crawl_depth",3)); order=0
    debug_dir=out_dir/"_debug"; debug_dir.mkdir(parents=True,exist_ok=True) if cfg.get("debug") else None
    log("\n=== SKANOWANIE STRUKTURY ===")
    emit(ev.EVENT_SCAN_START,start_url=start)
    while queue and len(found)<maxn:
        url,depth=queue.pop(0)
        if url in seen or depth>depthmax:continue
        seen.add(url)
        try:page.goto(url,wait_until="domcontentloaded",timeout=90000);page.wait_for_timeout(700)
        except Exception as e:log(f"[WARN] {url}: {e}");continue
        if looks_like_login(page):raise RuntimeError("Sesja wygasła podczas skanowania.")
        title=extract_title(page,urlparse(page.url).path.rsplit('/',1)[-1] or "Materiał")
        category=extract_category(page,page.url)
        items=link_candidates(page,cfg)
        scored=[]
        for item in items:
            u=canonical(urljoin(page.url,item.get("href") or "")); s=lesson_score(item,cfg,start)
            if s>0:scored.append((s,u,item))
            # Do płytkiego skanowania dodajemy tylko sensowne strony kursowe/nawigacyjne.
            navtxt=(str(item.get("text") or "")+" "+u).lower()
            if depth<depthmax and same_origin(u,start) and any(h in navtxt for h in LESSON_HINTS):
                if u not in seen and u not in [x[0] for x in queue]:queue.append((u,depth+1))
        # Startowa strona sama może być materiałem jeśli zawiera player.
        try: has_media=page.locator("video,audio,iframe").count()>0
        except Exception: has_media=False
        if (url!=start and (scored or has_media)) or (url==start and has_media and not scored):
            lid=stable_id(page.url)
            if lid not in found:
                order+=1;found[lid]=Lesson(canonical(page.url),lid,title,category,order);log(f"[{order:03d}] {category} / {title}")
        for s,u,item in sorted(scored,key=lambda x:x[0],reverse=True):
            lid=stable_id(u)
            if lid not in found:
                # Nie otwieramy tutaj każdego linku od razu; kolejka zweryfikuje tytuł/category.
                if u not in seen and u not in [x[0] for x in queue]:queue.append((u,depth+1))
        if debug_dir:
            (debug_dir/f"page_{len(seen):04d}.json").write_text(json.dumps({"url":page.url,"title":title,"depth":depth,"candidate_links":[{"score":lesson_score(x,cfg,start),**x} for x in items[:500]]},ensure_ascii=False,indent=2),encoding="utf-8")
    # Fallback: jeśli wykryto linki, ale strony nie miały playera podczas skanowania, potraktuj wysoko punktowane URL z debugowanego przebiegu jako lekcje.
    if not found:
        page.goto(start,wait_until="domcontentloaded",timeout=90000); page.wait_for_timeout(500)
        candidates=sorted([(lesson_score(x,cfg,start),canonical(urljoin(start,x.get("href") or "")),x) for x in link_candidates(page,cfg)],reverse=True,key=lambda z:z[0])
        seen_u=set()
        for s,u,x in candidates:
            if s<=0 or u in seen_u:continue
            seen_u.add(u); order+=1; found[stable_id(u)]=Lesson(u,stable_id(u),x.get("text") or f"Materiał {order}","Bez kategorii",order)
            if len(found)>=maxn:break
    lessons=list(sorted(found.values(),key=lambda x:x.order))
    log(f"Znaleziono materiałów: {len(lessons)}")
    emit(ev.EVENT_SCAN_DONE,count=len(lessons))
    return lessons


def setup_capture(page):
    captured=[]
    def on_response(resp):
        try:
            u=resp.url;ct=(resp.headers.get("content-type") or "").lower();low=u.lower().split("?")[0]
            if resp.request.resource_type=="media" or "video/" in ct or "audio/" in ct or "mpegurl" in ct or "dash+xml" in ct or low.endswith(MEDIA_EXTS+STREAM_EXTS):
                if not u.startswith("blob:"):captured.append((u,ct))
        except Exception:pass
    page.on("response",on_response);return captured,on_response


def try_play(page):
    started=False
    for frame in page.frames:
        try:
            media=frame.locator("video,audio")
            for i in range(min(media.count(),5)):
                try:media.nth(i).evaluate("el=>{el.muted=false; const p=el.play(); if(p)p.catch(()=>{});}");started=True
                except Exception:pass
        except Exception:pass
        for sel in ["button[aria-label*='play' i]","button[title*='play' i]",".vjs-big-play-button",".plyr__control--overlaid",".mejs__play button","[class*='play'][role='button']"]:
            try:
                loc=frame.locator(sel)
                for i in range(min(loc.count(),3)):
                    try:loc.nth(i).click(timeout=700);started=True
                    except Exception:pass
            except Exception:pass
    return started


def media_status(page):
    states=[]
    for frame in page.frames:
        try:
            arr=frame.locator("video,audio").evaluate_all("els=>els.map(e=>({paused:e.paused,ended:e.ended,duration:Number.isFinite(e.duration)?e.duration:null,currentTime:e.currentTime,readyState:e.readyState,mediaKeys:!!e.mediaKeys}))")
            states.extend(arr)
        except Exception:pass
    return states


def detect_drm(page):
    for st in media_status(page):
        if st.get("mediaKeys"):return True
    return False


def rank_media(captured):
    uniq=[];seen=set()
    for u,ct in captured:
        if u in seen:continue
        seen.add(u);low=u.lower().split("?")[0]
        if low.endswith((".ts",".m4s",".cmfv",".cmfa")):continue
        score=100 if low.endswith(MEDIA_EXTS) else 90 if ("video/" in ct or "audio/" in ct) else 70 if (low.endswith(".m3u8") or "mpegurl" in ct) else 60 if (low.endswith(".mpd") or "dash+xml" in ct) else 10
        uniq.append((score,u,ct))
    return [(u,ct) for _,u,ct in sorted(uniq,reverse=True)]


def req_session(ctx):
    s=requests.Session()
    for c in ctx.cookies():
        try:s.cookies.set(c["name"],c["value"],domain=c.get("domain"),path=c.get("path","/"))
        except Exception:s.cookies.set(c["name"],c["value"])
    return s


def ua(page):
    try:return page.evaluate("() => navigator.userAgent")
    except Exception:return "Mozilla/5.0"


def direct_download(ctx,page,url,target_noext):
    s=req_session(ctx);hdr={"Referer":page.url,"User-Agent":ua(page)}
    with s.get(url,headers=hdr,stream=True,timeout=60) as r:
        r.raise_for_status();ct=r.headers.get("content-type","");low=urlparse(url).path.lower();ext=next((x for x in MEDIA_EXTS if low.endswith(x)),None) or (".mp3" if "audio/mpeg" in ct else ".m4a" if "audio/" in ct else ".mp4")
        t=target_noext.with_suffix(ext);t.parent.mkdir(parents=True,exist_ok=True)
        with t.open("wb") as f:
            for chunk in r.iter_content(1024*1024):
                if chunk:f.write(chunk)
    return t


def manifest_text(ctx,page,url):
    r=req_session(ctx).get(url,headers={"Referer":page.url,"User-Agent":ua(page)},timeout=30);r.raise_for_status();return r.text


def protected_manifest(text):
    u=text.upper();return any(x in u for x in ("#EXT-X-KEY","CONTENTPROTECTION","WIDEVINE","PLAYREADY","FAIRPLAY"))


def stream_download(ctx,page,url,target):
    try:m=manifest_text(ctx,page,url)
    except Exception as e:return None,f"Nie można odczytać manifestu: {e}",False
    if protected_manifest(m):return None,"Wykryto szyfrowanie/DRM/ContentProtection.",True
    ff=imageio_ffmpeg.get_ffmpeg_exe();cookie="; ".join(f"{c['name']}={c['value']}" for c in ctx.cookies());headers=f"Referer: {page.url}\r\nUser-Agent: {ua(page)}\r\n"+(f"Cookie: {cookie}\r\n" if cookie else "")
    target.parent.mkdir(parents=True,exist_ok=True);p=subprocess.run([ff,"-y","-loglevel","warning","-headers",headers,"-i",url,"-c","copy",str(target)],capture_output=True,text=True)
    return (target,None,False) if p.returncode==0 else (None,(p.stderr or "FFmpeg error")[-1500:],False)


def resolve_monitor_spec(spec=None):
    """Resolve a persisted monitor spec against current MSS monitor geometry."""
    spec = spec or {"index": 1}
    with mss.mss() as sct:
        monitors = [dict(m) for m in sct.monitors[1:]]
    if not monitors:
        raise RuntimeError("Nie wykryto żadnego monitora.")

    wanted_geom = tuple(spec.get(k) for k in ("left", "top", "width", "height"))
    if all(v is not None for v in wanted_geom):
        for idx, mon in enumerate(monitors, 1):
            geom = (mon.get("left"), mon.get("top"), mon.get("width"), mon.get("height"))
            if geom == wanted_geom:
                mon["index"] = idx
                return mon

    idx = int(spec.get("index", 1) or 1)
    idx = max(1, min(idx, len(monitors)))
    mon = monitors[idx - 1]
    mon["index"] = idx
    return mon


def resolve_audio_speaker(device_name):
    if not device_name or device_name == "__default__":
        return sc.default_speaker()
    wanted = str(device_name).strip().lower()
    speakers = list(sc.all_speakers())
    for sp in speakers:
        if str(sp.name).strip().lower() == wanted:
            return sp
    for sp in speakers:
        if wanted in str(sp.name).lower() or str(sp.name).lower() in wanted:
            return sp
    raise RuntimeError(f"Nie znaleziono urządzenia audio: {device_name}")


def chromium_window_args(cfg):
    if not cfg.get("browser_on_record_monitor", True):
        return []
    mon = resolve_monitor_spec(cfg.get("record_monitor"))
    return [
        f"--window-position={int(mon['left'])},{int(mon['top'])}",
        f"--window-size={int(mon['width'])},{int(mon['height'])}",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
    ]


def position_browser_window(ctx, page, cfg):
    """Use Chromium CDP to keep the controlled browser on the chosen monitor."""
    if not cfg.get("browser_on_record_monitor", True):
        return
    mon = resolve_monitor_spec(cfg.get("record_monitor"))
    try:
        cdp = ctx.new_cdp_session(page)
        info = cdp.send("Browser.getWindowForTarget")
        window_id = info.get("windowId")
        if window_id is not None:
            cdp.send("Browser.setWindowBounds", {
                "windowId": window_id,
                "bounds": {
                    "windowState": "normal",
                    "left": int(mon["left"]),
                    "top": int(mon["top"]),
                    "width": int(mon["width"]),
                    "height": int(mon["height"]),
                },
            })
    except Exception as e:
        log(f"[WARN] Nie udało się wymusić położenia okna Chromium przez CDP: {e}")


class ScreenAudioRecorder:
    def __init__(self,output:Path,fps=10,monitor_spec=None,audio_device="__default__"):
        self.output=output;self.fps=fps;self.monitor_spec=monitor_spec or {"index":1};self.audio_device=audio_device;self.stop_evt=threading.Event();self.video_proc=None;self.audio_thread=None;self.video_thread=None;self.tmpv=output.with_suffix(".screen.tmp.mp4");self.tmpa=output.with_suffix(".audio.tmp.wav");self.audio_error=None;self.video_error=None;self.audio_started=False;self.last_audio_activity=None;self.monitor=None
    def start(self):
        self.output.parent.mkdir(parents=True,exist_ok=True)
        self.monitor=resolve_monitor_spec(self.monitor_spec)
        mon=self.monitor;w,h=mon["width"],mon["height"];ff=imageio_ffmpeg.get_ffmpeg_exe()
        cmd=[ff,"-y","-loglevel","error","-f","rawvideo","-pix_fmt","bgra","-s",f"{w}x{h}","-r",str(self.fps),"-i","-","-an","-c:v","libx264","-preset","veryfast","-crf","24","-pix_fmt","yuv420p",str(self.tmpv)]
        self.video_proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        self.video_thread=threading.Thread(target=self._video,daemon=True);self.audio_thread=threading.Thread(target=self._audio,daemon=True);self.video_thread.start();self.audio_thread.start()
    def _video(self):
        try:
            with mss.mss() as sct:
                mon=self.monitor or resolve_monitor_spec(self.monitor_spec);interval=1.0/self.fps;next_t=time.perf_counter()
                while not self.stop_evt.is_set():
                    frame=sct.grab(mon);self.video_proc.stdin.write(frame.raw);next_t+=interval;time.sleep(max(0,next_t-time.perf_counter()))
        except Exception as e:self.video_error=str(e)
        finally:
            try:self.video_proc.stdin.close()
            except Exception:pass
    def _audio(self):
        sr=48000
        try:
            speaker=resolve_audio_speaker(self.audio_device);loop=None
            for mic in sc.all_microphones(include_loopback=True):
                if speaker.name.lower() in mic.name.lower() or mic.name.lower() in speaker.name.lower():loop=mic;break
            if loop is None:
                # SoundCard zwykle potrafi utworzyć urządzenie loopback po nazwie głośnika.
                loop=sc.get_microphone(id=str(speaker.name),include_loopback=True)
            with wave.open(str(self.tmpa),"wb") as wf:
                wf.setnchannels(2);wf.setsampwidth(2);wf.setframerate(sr)
                with loop.recorder(samplerate=sr,channels=2) as rec:
                    while not self.stop_evt.is_set():
                        data=rec.record(numframes=4800)
                        arr=np.asarray(data)
                        rms=float(np.sqrt(np.mean(np.square(arr)))) if arr.size else 0.0
                        if rms>0.004:
                            self.audio_started=True;self.last_audio_activity=time.time()
                        pcm=np.clip(arr,-1,1);pcm=(pcm*32767).astype(np.int16);wf.writeframes(pcm.tobytes())
        except Exception as e:self.audio_error=str(e)
    def stop(self):
        self.stop_evt.set()
        if self.video_thread:self.video_thread.join(timeout=5)
        if self.audio_thread:self.audio_thread.join(timeout=5)
        if self.video_proc:
            try:self.video_proc.wait(timeout=10)
            except Exception:self.video_proc.kill()
        ff=imageio_ffmpeg.get_ffmpeg_exe()
        if self.tmpv.exists() and self.tmpa.exists() and self.tmpa.stat().st_size>1000:
            p=subprocess.run([ff,"-y","-loglevel","error","-i",str(self.tmpv),"-i",str(self.tmpa),"-c:v","copy","-c:a","aac","-shortest",str(self.output)],capture_output=True,text=True)
            if p.returncode!=0:self.video_error=(self.video_error or "")+" merge: "+(p.stderr or "")[-800:]
        elif self.tmpv.exists():self.tmpv.replace(self.output)
        for x in (self.tmpv,self.tmpa):
            try:
                if x.exists():x.unlink()
            except Exception:pass
        return self.output if self.output.exists() else None


def record_fallback(page,lesson_dir,lesson,cfg):
    if detect_drm(page):return None,"Wykryto aktywne EME/DRM. Nagrywanie nie zostało uruchomione.",True
    out=lesson_dir/f"{lesson.order:03d}_{safe_name(lesson.title)}_recorded.mp4";rec=ScreenAudioRecorder(out,int(cfg.get("record_fps",10)),cfg.get("record_monitor"),cfg.get("record_audio_device","__default__"))
    mon=resolve_monitor_spec(cfg.get("record_monitor"))
    log(f"Fallback: nagrywam Monitor {mon['index']} ({mon['width']}x{mon['height']} @ {mon['left']},{mon['top']}) + audio loopback: {cfg.get('record_audio_device','__default__')}.")
    rec.start();page.wait_for_timeout(400);started=try_play(page)
    maxsec=int(cfg.get("record_max_minutes",180))*60;start=time.time();ever_active=False;last_progress=time.time();last_ct=-1
    try:
        while time.time()-start<maxsec:
            page.wait_for_timeout(1000);states=media_status(page)
            if any(s.get("mediaKeys") for s in states):
                rec.stop();
                try:out.unlink()
                except Exception:pass
                return None,"W trakcie odtwarzania wykryto EME/DRM. Nagrywanie przerwano.",True
            playable=[s for s in states if s.get("duration") and s.get("duration",0)>1]
            if playable:
                ever_active=True;ct=max(float(s.get("currentTime") or 0) for s in playable);dur=max(float(s.get("duration") or 0) for s in playable)
                if ct>last_ct+0.2:last_progress=time.time();last_ct=ct
                if all(s.get("ended") or float(s.get("currentTime") or 0)>=float(s.get("duration") or 0)-1.0 for s in playable):break
                # Jeśli odtwarzanie stoi przez 90 s po starcie, nie nagrywaj bez końca.
                if time.time()-last_progress>90:break
            elif ever_active and time.time()-last_progress>30:
                break
            elif not states:
                elapsed=time.time()-start
                # Dla niestandardowego playera bez widocznego <video>/<audio> używamy aktywności audio.
                if rec.audio_started and rec.last_audio_activity and elapsed>30 and time.time()-rec.last_audio_activity>60:
                    break
                if rec.audio_error and elapsed>90:
                    break
                if not rec.audio_started and elapsed>120:
                    break
        path=rec.stop();notes=[]
        if rec.audio_error:notes.append("audio: "+rec.audio_error)
        if rec.video_error:notes.append("video: "+rec.video_error)
        return path,("; ".join(notes) if notes else None),False
    except Exception as e:
        path=rec.stop();return path,f"Błąd monitorowania odtwarzania: {e}",False


def find_download(page,ctx,lesson,lesson_dir,cfg):
    captured,handler=setup_capture(page);page.wait_for_timeout(600);try_play(page);page.wait_for_timeout(int(cfg.get("capture_seconds",8))*1000)
    try:page.remove_listener("response",handler)
    except Exception:pass
    if detect_drm(page):return None,None,"Wykryto EME/DRM.",True
    try:
        dom=page.eval_on_selector_all("video[src],audio[src],video source[src],audio source[src]","els=>els.map(x=>x.src||x.getAttribute('src')).filter(x=>x&&!x.startsWith('blob:'))")
    except Exception:dom=[]
    candidates=rank_media(captured); seen={u for u,_ in candidates}
    for u in reversed(dom):
        if u not in seen:candidates.insert(0,(u,""));seen.add(u)
    errors=[]
    for u,ct in candidates[:12]:
        low=u.lower().split("?")[0]
        try:
            if low.endswith(STREAM_EXTS):
                p,e,prot=stream_download(ctx,page,u,lesson_dir/f"{lesson.order:03d}_{safe_name(lesson.title)}.mp4")
                if prot:return None,u,e,True
                if p:return p,u,None,False
                errors.append(e)
            else:
                p=direct_download(ctx,page,u,lesson_dir/f"{lesson.order:03d}_{safe_name(lesson.title)}");return p,u,None,False
        except Exception as e:errors.append(str(e))
    return None,(candidates[0][0] if candidates else None),(" | ".join(errors[-3:]) if errors else "Nie znaleziono bezpośredniego źródła mediów."),False


class Transcriber:
    def __init__(self,name,lang):self.name=name;self.lang=None if lang in ("","auto",None) else lang;self._m=None
    def model(self):
        if self._m is None:
            try:
                import ctranslate2;cuda=ctranslate2.get_cuda_device_count()>0
            except Exception:cuda=False
            dev="cuda" if cuda else "cpu";ctype="float16" if cuda else "int8";log(f"Ładowanie Whisper {self.name}: {dev}/{ctype}");self._m=WhisperModel(self.name,device=dev,compute_type=ctype)
        return self._m
    def run(self,media,title,outdir):
        segs,info=self.model().transcribe(str(media),language=self.lang,vad_filter=True,beam_size=5);plain=[];rows=[]
        for s in segs:
            t=(s.text or "").strip()
            if t:plain.append(t);rows.append(f"[{fmt(s.start)} → {fmt(s.end)}] {t}")
        txt=outdir/(media.stem+".txt");md=outdir/(media.stem+".md");txt.write_text("\n".join(plain)+"\n",encoding="utf-8");md.write_text(f"# {title}\n\nŹródło lokalne: `{media.name}`\n\nJęzyk: `{getattr(info,'language',self.lang)}`\n\n## Transkrypcja\n\n"+"\n\n".join(rows)+"\n",encoding="utf-8");return txt,md

def fmt(x):
    x=int(max(0,x));h,r=divmod(x,3600);m,s=divmod(r,60);return f"{h:02d}:{m:02d}:{s:02d}"


def write_index(out,lessons,portal):
    (out/"index.json").write_text(json.dumps([asdict(x) for x in lessons],ensure_ascii=False,indent=2),encoding="utf-8")
    cats={}
    for l in lessons:cats.setdefault(l.category or "Bez kategorii",[]).append(l)
    md=[f"# {portal}",""]
    sections=[]
    for cat,items in cats.items():
        md += [f"## {cat}",""] ; lis=[]
        for l in items:
            ln=[f"{l.order:03d}. **{l.title}**"]
            if l.media_file:ln.append(f"[nagranie]({Path(l.media_file).as_posix()})")
            if l.transcript_md:ln.append(f"[transkrypcja]({Path(l.transcript_md).as_posix()})")
            if l.note:ln.append("— "+l.note)
            md.append(" - ".join(ln))
            links=[]
            if l.media_file:links.append(f'<a href="{html.escape(Path(l.media_file).as_posix())}">nagranie</a>')
            if l.transcript_md:links.append(f'<a href="{html.escape(Path(l.transcript_md).as_posix())}">transkrypcja</a>')
            lis.append(f'<li><b>{l.order:03d} {html.escape(l.title)}</b><div>{" · ".join(links) or "brak pliku"}</div><small>{html.escape(l.note or "")}</small></li>')
        md.append("");sections.append(f"<section><h2>{html.escape(cat)}</h2><ol>{''.join(lis)}</ol></section>")
    (out/"INDEX.md").write_text("\n".join(md),encoding="utf-8")
    (out/"index.html").write_text(f'''<!doctype html><html lang="pl"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{html.escape(portal)}</title><style>body{{font-family:system-ui;max-width:1100px;margin:35px auto;padding:0 20px}}h2{{margin-top:35px;border-bottom:1px solid #ddd;padding-bottom:8px}}li{{padding:11px 0}}small{{display:block;color:#777;margin-top:4px}}a{{margin-right:8px}}</style><body><h1>{html.escape(portal)}</h1><p>Lokalne archiwum materiałów i transkrypcji.</p>{''.join(sections)}</body></html>''',encoding="utf-8")


def process(ctx,page,cfg,out,lessons,state):
    tr=Transcriber(cfg["whisper_model"],cfg.get("whisper_language"))
    emit(ev.EVENT_PROCESS_START,total=len(lessons))
    for idx,l in enumerate(lessons,1):
        old=state.get(l.lesson_id)
        if old.get("status")=="done":
            for k,v in old.items():
                if hasattr(l,k):setattr(l,k,v)
            log(f"[SKIP {idx}/{len(lessons)}] {l.title}")
            emit(ev.EVENT_LESSON_DONE,index=idx,total=len(lessons),title=l.title,status="skipped")
            continue
        catdir=out/safe_name(l.category);ldir=catdir/f"{l.order:03d}_{safe_name(l.title)}";ldir.mkdir(parents=True,exist_ok=True)
        log(f"\n=== [{idx}/{len(lessons)}] {l.title} ===")
        try:
            page.goto(l.url,wait_until="domcontentloaded",timeout=90000);page.wait_for_timeout(900)
            if looks_like_login(page):raise RuntimeError("Sesja logowania wygasła.")
            # Aktualizacja tytułu/kategorii po wejściu w lekcję.
            l.title=extract_title(page,l.title);l.category=extract_category(page,page.url);catdir=out/safe_name(l.category);ldir=catdir/f"{l.order:03d}_{safe_name(l.title)}";ldir.mkdir(parents=True,exist_ok=True)
            media=None;protected=False;notes=[]
            if cfg.get("download_media",True):
                media,l.media_url,note,protected=find_download(page,ctx,l,ldir,cfg)
                if note:notes.append(note)
                if media:log(f"Pobrano: {media.name}")
            if not media and cfg.get("record_fallback",True) and not protected:
                media,note,protected2=record_fallback(page,ldir,l,cfg);protected=protected or protected2
                if note:notes.append(note)
                if media:log(f"Nagrano lokalnie: {media.name}")
            if media:
                l.media_file=str(media.relative_to(out))
                if cfg.get("transcribe",True):
                    txt,md=tr.run(media,l.title,ldir);l.transcript_txt=str(txt.relative_to(out));l.transcript_md=str(md.relative_to(out));log(f"Transkrypcja: {txt.name}")
                l.status="done"
            else:
                l.status="protected" if protected else "media_unavailable"
            l.note=" | ".join(x for x in notes if x) or None
        except Exception as e:l.status="error";l.note=str(e);log(f"[ERROR] {e}")
        (ldir/"metadata.json").write_text(json.dumps(asdict(l),ensure_ascii=False,indent=2),encoding="utf-8");state.put(l);write_index(out,lessons,cfg["portal_name"])
        emit(ev.EVENT_LESSON_DONE,index=idx,total=len(lessons),title=l.title,status=l.status)


STAGE_STOP="stop"


def final_stage(args)->str:
    """Ustal, na którym etapie agent ma zakończyć pracę.

    --after-login pozwala GUI przejść z logowania prosto do skanowania lub do
    pełnego procesu BEZ ponownego otwierania przeglądarki.
    """
    if args.login_only:
        return args.after_login or STAGE_STOP
    if args.discover_only:
        return ev.STAGE_DISCOVER
    return ev.STAGE_PROCESS


def run_agent(args)->None:
    cfg=load_config(Path(args.config));out=Path(os.path.expandvars(cfg["output_dir"])).expanduser().resolve();prof=Path(os.path.expandvars(cfg["browser_profile_dir"])).expanduser().resolve();out.mkdir(parents=True,exist_ok=True);prof.mkdir(parents=True,exist_ok=True)
    stage=final_stage(args)
    statep=out/".state.json";
    if args.reset_state and statep.exists():statep.unlink()
    state=State(statep)
    emit(ev.EVENT_AGENT_START,stage=stage,portal_name=cfg.get("portal_name"),output_dir=str(out))
    with sync_playwright() as p:
        args_chromium=chromium_window_args(cfg)
        if args_chromium:
            mon=resolve_monitor_spec(cfg.get("record_monitor"));log(f"Chromium: Monitor {mon['index']} ({mon['width']}x{mon['height']} @ {mon['left']},{mon['top']}).")

        try:
            ctx=p.chromium.launch_persistent_context(user_data_dir=str(prof),channel="chrome",headless=False,no_viewport=True,accept_downloads=True,args=args_chromium)
        except Exception as e:
            raise RuntimeError("Nie udało się uruchomić Google Chrome. Upewnij się, że Chrome jest zainstalowany. Szczegóły: " + str(e))
        try:
            page=ctx.pages[0] if ctx.pages else ctx.new_page();position_browser_window(ctx,page,cfg)
            emit(ev.EVENT_BROWSER_READY,url=cfg["start_url"])
            page.goto(cfg["start_url"],wait_until="domcontentloaded",timeout=90000);page.wait_for_timeout(800)
            login_stage(page,cfg);position_browser_window(ctx,page,cfg)
            if stage==STAGE_STOP:
                log("\nEtap zakończony: logowanie. Możesz teraz uruchomić skanowanie lub pełny proces.")
                emit(ev.EVENT_FINISHED,stage=ev.STAGE_LOGIN,output_dir=str(out))
                return
            lessons=discover_lessons(page,cfg,out);write_index(out,lessons,cfg["portal_name"])
            if not lessons:raise RuntimeError("Nie znaleziono materiałów. Ustaw regex URL lub selektor CSS w zakładce Wykrywanie materiałów.")
            if stage==ev.STAGE_DISCOVER:
                log(f"\nEtap zakończony: skanowanie. Katalog: {out}")
                emit(ev.EVENT_FINISHED,stage=ev.STAGE_DISCOVER,count=len(lessons),output_dir=str(out))
                return
            process(ctx,page,cfg,out,lessons,state);write_index(out,lessons,cfg["portal_name"])
        finally:
            ctx.close()
    log(f"\nGOTOWE. Katalog: {out}\nIndeks: {out/'index.html'}")
    emit(ev.EVENT_FINISHED,stage=ev.STAGE_PROCESS,output_dir=str(out),index=str(out/"index.html"))


def main():
    ap=argparse.ArgumentParser();ap.add_argument("--config",required=True);ap.add_argument("--login-only",action="store_true");ap.add_argument("--discover-only",action="store_true")
    ap.add_argument("--after-login",choices=[STAGE_STOP,ev.STAGE_DISCOVER,ev.STAGE_PROCESS],default=None,help="Co zrobić po udanym logowaniu w trybie --login-only.")
    ap.add_argument("--reset-state",action="store_true");args=ap.parse_args()
    try:
        run_agent(args)
    except Exception as e:
        log(f"\n[BŁĄD] {e}")
        emit(ev.EVENT_FAILED,error=str(e))
        raise SystemExit(1)


if __name__=="__main__":main()
