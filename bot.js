// 1. Nastavenia - sessionStorage udrží históriu aj pri prechode na inú podstránku
const STORAGE_KEY = 'vegnella_chat_session';
const TUNNEL_URL = "https://vegnella-bot.onrender.com/api/chat";

let chatHistory = loadHistory();

function loadHistory() {
    try {
        const savedData = sessionStorage.getItem(STORAGE_KEY);
        return savedData ? JSON.parse(savedData) : [];
    } catch (e) {
        return [];
    }
}

function saveHistory() {
    try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(chatHistory));
    } catch (e) {
        console.error("Chyba pri ukladaní do sessionStorage", e);
    }
}

function clearHistory() {
    chatHistory = [];
    try {
        sessionStorage.removeItem(STORAGE_KEY);
    } catch (e) {}
}

// 2. Vloženie HTML a responsive CSS štruktúry chatu
document.addEventListener("DOMContentLoaded", function () {
    if (document.getElementById('vegnella-chat-widget')) return;

    const styleTag = document.createElement('style');
    styleTag.innerHTML = `
        /* Základné desktop štýly pre okno */
        #chat-window {
            display: none;
            width: 360px;
            height: 500px;
            background: #1e1e1e;
            color: #ffffff;
            border-radius: 16px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.4);
            flex-direction: column;
            overflow: hidden;
            position: absolute;
            bottom: 80px;
            right: 0;
            border: 1px solid #333;
        }

        /* Responsive štýly pre mobilné zariadenia (pod 600px) */
        @media (max-width: 600px) {
            #vegnella-chat-widget {
                bottom: 20px !important;
                right: 20px !important;
            }
            
            #chat-window {
                position: fixed !important;
                top: 0 !important;
                left: 0 !important;
                right: 0 !important;
                bottom: 0 !important;
                width: 100vw !important;
                height: 100dvh !important;
                border-radius: 0 !important;
                border: none !important;
                z-index: 999999 !important;
            }

            body.chat-open {
                overflow: hidden !important;
            }
        }
    `;
    document.head.appendChild(styleTag);

    const chatHTML = `
    <div id="vegnella-chat-widget" style="position: fixed; bottom: 20px; right: 20px; z-index: 10000; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        <button id="chat-toggle-btn" onclick="toggleVegnellaChat()" style="position: relative; background-color: #df824c; color: white; border: none; border-radius: 50%; padding: 0; width: 60px; height: 60px; font-size: 24px; cursor: pointer; box-shadow: 0 5px 15px rgba(0,0,0,0.3); display: flex; align-items: center; justify-content: center;">
            <span id="chat-icon">🌿</span>
            <span id="chat-notification" style="position: absolute; top: -5px; right: -5px; background-color: #ff3b30; color: white; border-radius: 50%; width: 22px; height: 22px; font-size: 14px; display: flex; align-items: center; justify-content: center; font-weight: bold; border: 2px solid white;">1</span>
        </button>

        <div id="chat-window">
            <div style="background: #df824c; color: white; padding: 16px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; font-size: 16px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span>🌿</span>
                    <span>Vegnella Asistent</span>
                </div>
                <span onclick="closeAndResetChat()" style="cursor: pointer; font-size: 24px; padding: 0 8px; line-height: 1;" title="Zatvoriť a vymazat konverzáciu">✕</span>
            </div>

            <div id="chatBox" style="flex: 1; padding: 15px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; background: #121212;">
                </div>

            <div style="display: flex; border-top: 1px solid #2a2a2a; padding: 12px; background: #1e1e1e; gap: 8px; align-items: center;">
                <input type="text" id="userInput" placeholder="Napíš správu..." onkeypress="if(event.key==='Enter') sendMessage()" style="flex: 1; border: 1px solid #333; background: #2a2a2a; color: white; padding: 12px 16px; border-radius: 24px; outline: none; font-size: 15px;">
                <button onclick="sendMessage()" style="background: #f8b02b; color: white; border: none; width: 44px; height: 44px; border-radius: 50%; cursor: pointer; font-weight: bold; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0;">➔</button>
            </div>
        </div>
    </div>
    `;

    document.body.insertAdjacentHTML("beforeend", chatHTML);

    // Načítame správy pri prechode na inú stránku
    renderMessages();
});

// Funkcia na prekreslenie správ
function renderMessages() {
    const chatBox = document.getElementById('chatBox');
    if (!chatBox) return;

    chatBox.innerHTML = ''; 

    // Základná privítacia správa
    const welcomeDiv = document.createElement('div');
    welcomeDiv.style.cssText = 'background: #2a2a2a; color: #e0e0e0; padding: 12px 16px; border-radius: 16px; max-width: 80%; font-size: 14px; align-self: flex-start; word-wrap: break-word; text-align: left; line-height: 1.4;';
    welcomeDiv.innerText = 'Ahoj! Som tvoj asistent z bistra Vegnella. Čo ti môžem dnes ponúknuť?';
    chatBox.appendChild(welcomeDiv);

    if (chatHistory && chatHistory.length > 0) {
        chatHistory.forEach(msg => {
            appendMessageUI(msg.content, msg.role === 'user' ? 'user' : 'bot');
        });
    }

    setTimeout(() => {
        chatBox.scrollTop = chatBox.scrollHeight;
    }, 50);
}

// 3. Prepínanie bubliny (KLIKNUTIE NA KRÚŽOK) - ZACHOVÁVA HISTÓRIU
function toggleVegnellaChat() {
    const win = document.getElementById('chat-window');
    const notification = document.getElementById('chat-notification');
    const toggleBtn = document.getElementById('chat-toggle-btn');
    if (!win) return;

    const isHidden = win.style.display === 'none' || win.style.display === '';
    
    if (isHidden) {
        win.style.display = 'flex';
        document.body.classList.add('chat-open');
        
        if (notification) notification.style.display = 'none';
        
        if (window.innerWidth <= 600 && toggleBtn) {
            toggleBtn.style.display = 'none';
        }

        const chatBox = document.getElementById('chatBox');
        if (chatBox) {
            setTimeout(() => {
                chatBox.scrollTop = chatBox.scrollHeight;
            }, 50);
        }
    } else {
        // Ak sa klikne na krúžok na zavretie - LEN SKRYJEME OKNO (históriu nemažeme!)
        hideChatWindow();
    }
}

// Pomocná funkcia len pre skrytie okna (bez mazania pamäte)
function hideChatWindow() {
    const win = document.getElementById('chat-window');
    const toggleBtn = document.getElementById('chat-toggle-btn');
    
    if (win) win.style.display = 'none';
    if (toggleBtn) toggleBtn.style.display = 'flex';
    document.body.classList.remove('chat-open');
}

// 4. KLIKNUTIE IBA NA "✕" - ZATVORÍ OKNO A VYMAŽE HISTÓRIU
function closeAndResetChat() {
    hideChatWindow();
    clearHistory();
    renderMessages(); // zresetuje UI chat do pôvodného stavu
}

// 5. Odoslanie správy
async function sendMessage() {
    const input = document.getElementById('userInput');
    if (!input) return;
    
    const text = input.value.trim();
    if (!text) return;

    appendMessageUI(text, 'user');
    input.value = '';

    chatHistory.push({ role: "user", content: text });
    saveHistory();

    try {
        const response = await fetch(TUNNEL_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ messages: chatHistory })
        });

        const data = await response.json();
        const botReply = data.odpoved || "Ospravedlňujem sa, nepodarilo sa získať odpoveď.";
        
        appendMessageUI(botReply, 'bot');
        chatHistory.push({ role: "assistant", content: botReply });
        saveHistory();

    } catch (error) {
        appendMessageUI("Chyba spojenia so serverom.", 'bot');
        console.error(error);
    }
}

// 6. Vykreslenie bubliny v chate
function appendMessageUI(text, sender) {
    const chatBox = document.getElementById('chatBox');
    if (!chatBox) return;

    const msgDiv = document.createElement('div');
    msgDiv.style.cssText = 'padding: 12px 16px; border-radius: 16px; max-width: 80%; font-size: 14px; line-height: 1.4; white-space: pre-line; word-wrap: break-word; text-align: left;';

    if (sender === 'user') {
        msgDiv.style.background = '#2e7d32';
        msgDiv.style.color = '#ffffff';
        msgDiv.style.alignSelf = 'flex-end';
        msgDiv.style.borderBottomRightRadius = '4px';
    } else {
        msgDiv.style.background = '#2a2a2a';
        msgDiv.style.color = '#e0e0e0';
        msgDiv.style.alignSelf = 'flex-start';
        msgDiv.style.borderBottomLeftRadius = '4px';
    }

    msgDiv.innerText = text;
    chatBox.appendChild(msgDiv);
    
    chatBox.scrollTop = chatBox.scrollHeight;
}