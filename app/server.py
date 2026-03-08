"""
Screen Stream Server (удалённый сервер)
========================================
Запуск: python server.py
Браузер: https://kege-station.store
"""

import asyncio
from datetime import datetime

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from openai import AsyncOpenAI, APIConnectionError, APIStatusError
from pydantic import BaseModel
from fastapi import Request, Response

openai_client = AsyncOpenAI(
    base_url="http://xray:8000/v1",
    api_key="dummy",
)

# ── Настройки ──────────────────────────────────────────────────────────────────
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8080
GPT_MODEL   = "gpt-5"
# ───────────────────────────────────────────────────────────────────────────────

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

viewers:  set[WebSocket] = set()
overlays: set[WebSocket] = set()


async def broadcast_to_viewers(data: bytes):
    if not viewers:
        return

    async def send_one(ws: WebSocket):
        try:
            await asyncio.wait_for(ws.send_bytes(data), timeout=3.0)
        except Exception:
            viewers.discard(ws)

    await asyncio.gather(*[send_one(ws) for ws in set(viewers)])


async def broadcast_to_overlays(text: str):
    dead = set()
    for ws in overlays:
        try:
            await asyncio.wait_for(ws.send_text(text), timeout=3.0)
        except Exception:
            dead.add(ws)
    overlays.difference_update(dead)


class NotifyRequest(BaseModel):
    answer: str


@app.post("/api/notify-overlay")
async def notify_overlay(req: NotifyRequest):
    """Браузер присылает сюда ответ GPT → сервер рассылает всем оверлеям."""
    if req.answer:
        asyncio.create_task(broadcast_to_overlays(req.answer))
    return JSONResponse({"ok": True})


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})

@app.post("/v1/chat/completions")
async def proxy_chat_completions(req: Request):
    payload = await req.json()

    try:
        response = await openai_client.chat.completions.create(**payload)
        return JSONResponse(content=response.model_dump())

    except APIConnectionError as e:
        return JSONResponse(
            {"error": {"message": f"ChatMock недоступен проверьте контейнер chatmock, {e.message}."}},
            status_code=503,
        )
    except APIStatusError as e:
        return JSONResponse(
            {"error": {"message": e.message}},
            status_code=e.status_code,
        )
    except Exception as e:
        return JSONResponse(
            {"error": {"message": str(e) or e.__class__.__name__}},
            status_code=500
        )

HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Screen Stream</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0a0a0a; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
  header { padding: 10px 20px; background: #141414; border-bottom: 1px solid #2a2a2a; display: flex; align-items: center; gap: 12px; flex-shrink: 0; z-index: 10; }
  h1 { font-size: 14px; font-weight: 600; color: #fff; }
  .badge { font-size: 11px; padding: 2px 10px; border-radius: 20px; background: #222; color: #666; }
  .badge.live { background: #ff3b3b18; color: #ff5555; animation: pulse 1.5s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
  .spacer { flex: 1; }
  .hdr-btn { padding: 4px 12px; border-radius: 5px; border: 1px solid #333; cursor: pointer; font-size: 11px; background: #1e1e1e; color: #aaa; transition: background .15s; }
  .hdr-btn:hover { background: #2a2a2a; color: #ddd; }
  .main { flex: 1; display: flex; overflow: hidden; }
  .screen-pane { display: flex; align-items: center; justify-content: center; background: #0d0d0d; overflow: hidden; position: relative; transition: flex .3s ease; flex: 1; min-width: 80px; cursor: pointer; }
  .screen-pane img { max-width: 100%; max-height: 100%; border-radius: 4px; display: none; pointer-events: none; }
  .placeholder { text-align: center; color: #333; pointer-events: none; user-select: none; }
  .placeholder svg { width: 48px; height: 48px; margin-bottom: 10px; }
  .placeholder p { font-size: 12px; }
  .screen-pane::after { content: attr(data-hint); position: absolute; bottom: 10px; left: 50%; transform: translateX(-50%); background: #000a; color: #888; font-size: 11px; padding: 3px 10px; border-radius: 20px; opacity: 0; transition: opacity .2s; white-space: nowrap; pointer-events: none; }
  .screen-pane:hover::after { opacity: 1; }
  .divider { width: 4px; background: #1e1e1e; cursor: col-resize; flex-shrink: 0; transition: background .15s; position: relative; z-index: 5; }
  .divider:hover, .divider.dragging { background: #3a7bd5; }
  .divider::after { content: ''; position: absolute; top: 50%; left: 50%; transform: translate(-50%,-50%); width: 2px; height: 32px; background: #444; border-radius: 2px; }
  .gpt-pane { display: flex; flex-direction: column; background: #111; overflow: hidden; transition: flex .3s ease; flex: 1; min-width: 260px; }
  .gpt-inner { display: flex; flex-direction: column; height: 100%; padding: 16px; gap: 10px; min-width: 260px; }
  .gpt-title { font-size: 12px; font-weight: 600; color: #777; text-transform: uppercase; letter-spacing: .5px; flex-shrink: 0; }
  .chat-history { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; padding-right: 4px; }
  .chat-history::-webkit-scrollbar { width: 4px; }
  .chat-history::-webkit-scrollbar-thumb { background: #2a2a2a; border-radius: 2px; }
  .msg { display: flex; flex-direction: column; gap: 4px; }
  .msg-label { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .5px; color: #555; }
  .msg.user .msg-label { color: #3a7bd5; }
  .msg.assistant .msg-label { color: #4caf7d; }
  .msg-body { background: #1a1a1a; border-radius: 8px; padding: 10px 12px; font-size: 13px; line-height: 1.6; color: #ccc; white-space: pre-wrap; word-break: break-word; border: 1px solid #222; }
  .msg.user .msg-body { background: #0d1f35; border-color: #1a3a5c; }
  .msg.assistant .msg-body { background: #0d1a12; border-color: #1a3a25; }
  .msg.error .msg-body { background: #1a0d0d; border-color: #3a1a1a; color: #e05555; }
  .think-block { background: #15152a; border-left: 2px solid #2a2a5a; padding: 6px 10px; margin-bottom: 6px; border-radius: 0 4px 4px 0; color: #556; font-size: 11.5px; font-style: italic; }
  .msg.loading .msg-body { display: flex; align-items: center; gap: 6px; color: #555; font-style: italic; }
  .dots span { display: inline-block; width: 4px; height: 4px; background: #555; border-radius: 50%; animation: dot-blink 1.2s infinite; }
  .dots span:nth-child(2) { animation-delay: .2s; }
  .dots span:nth-child(3) { animation-delay: .4s; }
  @keyframes dot-blink { 0%,80%,100%{opacity:.2} 40%{opacity:1} }
  .input-area { display: flex; flex-direction: column; gap: 8px; flex-shrink: 0; border-top: 1px solid #1e1e1e; padding-top: 10px; }
  .input-row { display: flex; gap: 8px; align-items: flex-end; }
  .input-area textarea { flex: 1; background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px; color: #ddd; font-size: 13px; padding: 8px 12px; resize: none; font-family: inherit; outline: none; min-height: 40px; max-height: 120px; line-height: 1.5; transition: border-color .15s; }
  .input-area textarea:focus { border-color: #2a6496; }
  .send-btn { padding: 10px 20px; border-radius: 8px; border: none; cursor: pointer; font-size: 15px; font-weight: 600; background: #1a4a7a; color: #7ec8f0; transition: background .15s; white-space: nowrap; flex-shrink: 0; height: 52px; }
  .send-btn:hover { background: #1e5a9a; }
  .send-btn:disabled { opacity: .4; cursor: not-allowed; }
  .quick-btn { width: 100%; padding: 14px; border-radius: 8px; border: none; cursor: pointer; font-size: 16px; font-weight: 700; background: #1a5a2a; color: #5ddb80; transition: background .15s; }
  .quick-btn:hover { background: #1e6e34; }
  .quick-btn:disabled { opacity: .4; cursor: not-allowed; }
  .proxy-row { display: flex; align-items: center; gap: 8px; }
  .proxy-status { font-size: 10px; color: #555; flex: 1; }
  .proxy-status.ok { color: #4caf7d; }
  .proxy-status.err { color: #e05555; }
  .hint { font-size: 10px; color: #444; text-align: center; }
  footer { padding: 6px 20px; background: #0d0d0d; border-top: 1px solid #1a1a1a; display: flex; gap: 20px; font-size: 11px; color: #444; flex-shrink: 0; }
  footer span b { color: #666; }
</style>
</head>
<body>
<header>
  <h1>🖥 Screen Stream</h1>
  <span class="badge" id="status">Ожидание...</span>
  <div class="spacer"></div>
  <button class="hdr-btn" onclick="copyFrame()">📋 Копировать кадр</button>
  <button class="hdr-btn" onclick="toggleGPT()" id="gpt-toggle-btn">💬 Скрыть чат</button>
</header>
<div class="main" id="main">
  <div class="screen-pane" id="screen-pane" data-hint="Нажмите чтобы развернуть" onclick="handleScreenClick(event)">
    <img id="screen" alt="stream"/>
    <div class="placeholder" id="placeholder">
      <svg viewBox="0 0 24 24" fill="none" stroke="#333" stroke-width="1.2"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>
      <p>Ожидание клиента...</p>
    </div>
  </div>
  <div class="divider" id="divider"></div>
  <div class="gpt-pane" id="gpt-pane">
    <div class="gpt-inner">
      <div class="gpt-title">🤖 GPT — Анализ экрана</div>
      <div class="chat-history" id="chat-history">
        <div style="color:#333;font-size:12px;text-align:center;margin-top:20px;">Задайте вопрос — GPT проанализирует текущий кадр</div>
      </div>
      <div class="input-area">
        <button class="quick-btn" id="quick-btn" onclick="quickAsk()">⚡ Какой здесь ответ</button>
        <div class="input-row">
          <textarea id="prompt" rows="2" onkeydown="handleKey(event)">Какой здесь ответ</textarea>
          <button class="send-btn" id="ask-btn" onclick="askGPT()">▶ Спросить</button>
        </div>
        <div class="proxy-row">
          <div class="proxy-status" id="proxy-status">● gpt_proxy.py: проверка...</div>
        </div>
        <div class="hint">Enter — отправить &nbsp;·&nbsp; Shift+Enter — новая строка</div>
      </div>
    </div>
  </div>
</div>
<footer>
  <span>FPS: <b id="fps">—</b></span>
  <span>Кадров: <b id="frames">0</b></span>
</footer>
<script>
  // gpt_proxy.py должен быть запущен на вашем ПК
  const GPT_PROXY  = '/v1/chat/completions';
  const GPT_MODEL  = 'gpt-5';

  const imgEl=document.getElementById('screen'),placeholder=document.getElementById('placeholder'),statusBadge=document.getElementById('status'),fpsEl=document.getElementById('fps'),framesEl=document.getElementById('frames'),chatHistory=document.getElementById('chat-history'),askBtn=document.getElementById('ask-btn'),promptEl=document.getElementById('prompt'),screenPane=document.getElementById('screen-pane'),gptPane=document.getElementById('gpt-pane'),divider=document.getElementById('divider'),proxyStatus=document.getElementById('proxy-status');
  let frameCount=0,lastFpsTime=Date.now(),lastFpsCount=0,screenExpanded=false,gptVisible=true,wasDragging=false,lastFrameB64=null;

  // ── Проверка прокси ──
  async function checkProxy(){
    try{
      const r=await fetch('/health',{signal:AbortSignal.timeout(2000)});
      proxyStatus.textContent='● gpt_proxy.py: запущен ✓';
      proxyStatus.className='proxy-status ok';
    }catch(e){
      proxyStatus.textContent='● gpt_proxy.py: не запущен';
      proxyStatus.className='proxy-status err';
    }
  }
  checkProxy();
  setInterval(checkProxy,15000);

  // ── WebSocket стрим ──
  function connect(){
    const proto=location.protocol==='https:'?'wss':'ws';
    const ws=new WebSocket(`${proto}://${location.host}/ws/view`);
    ws.binaryType='arraybuffer';
    let ping=null;
    ws.onopen=()=>{
      statusBadge.textContent='● LIVE';statusBadge.className='badge live';
      ping=setInterval(()=>{if(ws.readyState===WebSocket.OPEN)ws.send('ping');},25000);
    };
    ws.onmessage=(e)=>{
      if(typeof e.data==='string')return;
      // Сохраняем кадр как base64 для GPT
      const arr=new Uint8Array(e.data);
      let bin='';arr.forEach(b=>bin+=String.fromCharCode(b));
      lastFrameB64=btoa(bin);
      const blob=new Blob([e.data],{type:'image/jpeg'});
      const url=URL.createObjectURL(blob);
      imgEl.onload=()=>URL.revokeObjectURL(url);
      imgEl.src=url;imgEl.style.display='block';placeholder.style.display='none';
      frameCount++;framesEl.textContent=frameCount;
      const now=Date.now();if(now-lastFpsTime>=1000){fpsEl.textContent=frameCount-lastFpsCount;lastFpsTime=now;lastFpsCount=frameCount;}
    };
    ws.onclose=()=>{clearInterval(ping);statusBadge.textContent='Отключено';statusBadge.className='badge';imgEl.style.display='none';placeholder.style.display='block';setTimeout(connect,2000);};
  }

  async function copyFrame(){
    try{const c=document.createElement('canvas');c.width=imgEl.naturalWidth;c.height=imgEl.naturalHeight;c.getContext('2d').drawImage(imgEl,0,0);c.toBlob(async b=>{await navigator.clipboard.write([new ClipboardItem({'image/png':b})]);});}catch(e){console.error(e);}
  }

  function handleScreenClick(e){if(wasDragging)return;if(!gptVisible)return;screenExpanded=!screenExpanded;screenPane.style.flex=screenExpanded?'3':'1';gptPane.style.flex='1';screenPane.setAttribute('data-hint',screenExpanded?'Нажмите чтобы свернуть':'Нажмите чтобы развернуть');}

  function toggleGPT(){gptVisible=!gptVisible;const btn=document.getElementById('gpt-toggle-btn');if(gptVisible){gptPane.style.flex='1';gptPane.style.minWidth='260px';divider.style.display='block';screenPane.style.flex=screenExpanded?'3':'1';btn.textContent='💬 Скрыть чат';screenPane.setAttribute('data-hint','Нажмите чтобы развернуть');}else{gptPane.style.flex='0';gptPane.style.minWidth='0';divider.style.display='none';screenPane.style.flex='1';screenExpanded=false;btn.textContent='💬 Показать чат';screenPane.setAttribute('data-hint','');}}

  divider.addEventListener('mousedown',(e)=>{e.preventDefault();wasDragging=false;const sx=e.clientX;divider.classList.add('dragging');const tw=document.getElementById('main').offsetWidth;const onMove=(e)=>{if(Math.abs(e.clientX-sx)>3)wasDragging=true;const sw=Math.max(100,Math.min(e.clientX,tw-260));screenPane.style.flex=`0 0 ${sw}px`;gptPane.style.flex=`0 0 ${tw-sw-4}px`;};const onUp=()=>{divider.classList.remove('dragging');document.removeEventListener('mousemove',onMove);document.removeEventListener('mouseup',onUp);setTimeout(()=>{wasDragging=false;},50);};document.addEventListener('mousemove',onMove);document.addEventListener('mouseup',onUp);});

  function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();askGPT();}}

  function setAllDisabled(v){askBtn.disabled=v;document.getElementById('quick-btn').disabled=v;promptEl.disabled=v;}

  function addMessage(role,content,isLoading=false){
    const stub=chatHistory.querySelector('div[style]');if(stub)stub.remove();
    const msg=document.createElement('div');msg.className=`msg ${role}${isLoading?' loading':''}`;
    const label=document.createElement('div');label.className='msg-label';label.textContent=role==='user'?'Вы':role==='assistant'?'GPT':'Ошибка';
    const body=document.createElement('div');body.className='msg-body';
    if(isLoading){body.innerHTML='GPT думает <span class="dots"><span></span><span></span><span></span></span>';}
    else if(role==='assistant'){renderAnswer(body,content);}
    else{body.textContent=content;}
    msg.appendChild(label);msg.appendChild(body);chatHistory.appendChild(msg);chatHistory.scrollTop=chatHistory.scrollHeight;return msg;
  }

  function renderAnswer(container,text){
    container.innerHTML='';
    text.split(/(<think>[\s\S]*?<\/think>)/g).forEach(part=>{
      if(part.startsWith('<think>')){const div=document.createElement('div');div.className='think-block';div.textContent='💭 '+part.replace(/<\/?think>/g,'').trim();container.appendChild(div);}
      else if(part.trim()){const span=document.createElement('span');span.textContent=part;container.appendChild(span);}
    });
  }

  async function callGPT(prompt){
    if(!lastFrameB64)throw new Error('Нет кадра — дождитесь подключения клиента');
    const resp=await fetch(GPT_PROXY,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({model:GPT_MODEL,messages:[{role:'user',content:[
        {type:'image_url',image_url:{url:`data:image/jpeg;base64,${lastFrameB64}`}},
        {type:'text',text:prompt}
      ]}]})
    });
    const data = await resp.json().catch(()=>null);

    if(!resp.ok){
      const msg = data?.error?.message || data?.detail || ('HTTP ' + resp.status);
      throw new Error(msg);
    }
    if(data?.error){
      throw new Error(data.error.message || String(data.error));
    }
    return data.choices[0].message.content;
  }

  async function notifyOverlay(answer){
    const clean=answer.replace(/<think>[\s\S]*?<\/think>/g,'').trim();
    try{await fetch('/api/notify-overlay',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({answer:clean})});}
    catch(e){console.warn('notify-overlay error:',e);}
  }

  async function quickAsk(){
    setAllDisabled(true);
    addMessage('user','Какой здесь ответ');
    const loading=addMessage('assistant','',true);
    try{
      const answer=await callGPT('Какой здесь ответ');
      loading.remove();addMessage('assistant',answer);
      notifyOverlay(answer);
    }catch(e){loading.remove();addMessage('error',e.message);}
    finally{setAllDisabled(false);}
  }

  async function askGPT(){
    const prompt=promptEl.value.trim();if(!prompt)return;
    setAllDisabled(true);
    const savedPrompt=prompt;
    promptEl.value='Какой здесь ответ';
    addMessage('user',savedPrompt);
    const loading=addMessage('assistant','',true);
    try{
      const answer=await callGPT(savedPrompt);
      loading.remove();addMessage('assistant',answer);
      notifyOverlay(answer);
    }catch(e){loading.remove();addMessage('error',e.message);}
    finally{setAllDisabled(false);promptEl.focus();}
  }

  connect();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML


@app.websocket("/ws/view")
async def ws_view(ws: WebSocket):
    await ws.accept()
    viewers.add(ws)
    try:
        while True:
            await ws.receive()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        viewers.discard(ws)


@app.websocket("/ws/overlay")
async def ws_overlay(ws: WebSocket):
    """client.py подключается сюда и получает ответы GPT для оверлея."""
    await ws.accept()
    overlays.add(ws)
    print(f"[{datetime.now():%H:%M:%S}] Оверлей подключился")
    try:
        while True:
            await ws.receive()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        overlays.discard(ws)
        print(f"[{datetime.now():%H:%M:%S}] Оверлей отключился")


@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    await ws.accept()
    print(f"[{datetime.now():%H:%M:%S}] Клиент подключился")
    try:
        while True:
            data = await ws.receive_bytes()
            await broadcast_to_viewers(data)
    except (WebSocketDisconnect, Exception) as e:
        print(f"[{datetime.now():%H:%M:%S}] Клиент отключился: {e}")


if __name__ == "__main__":
    print("🖥  Screen Stream Server")
    print(f"   Адрес: http://localhost:{SERVER_PORT}")
    print("-" * 40)
    uvicorn.run(
        app,
        host=SERVER_HOST,
        port=SERVER_PORT,
        log_level="warning",
        ws_ping_interval=None,
        ws_ping_timeout=None,
    )