const HOST = "com.coursearchiver.bridge";
let currentUrl = "";

function setStatus(text, cls = "") {
  const el = document.getElementById("status");
  el.textContent = text;
  el.className = "status " + cls;
}

function nativeMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(HOST, message, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response || {});
    });
  });
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  currentUrl = tab?.url || "";
  document.getElementById("url").textContent = currentUrl || "Brak URL bieżącej karty";
}

async function loadProfiles() {
  try {
    const response = await nativeMessage({cmd: "status"});
    if (!response.ok) throw new Error(response.error || "Brak odpowiedzi hosta");
    const select = document.getElementById("profile");
    select.innerHTML = "";
    const profiles = response.profiles || [];
    if (!profiles.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(utwórz profil w aplikacji)";
      select.appendChild(opt);
      document.getElementById("login").disabled = true;
      document.getElementById("scan").disabled = true;
      document.getElementById("run").disabled = true;
    } else {
      profiles.forEach((name) => {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        select.appendChild(opt);
      });
    }
    setStatus("Połączenie z aplikacją: OK", "ok");
  } catch (e) {
    setStatus("Brak połączenia z aplikacją: " + e.message, "err");
  }
}

async function launch(action) {
  if (!currentUrl || !/^https?:/i.test(currentUrl)) {
    setStatus("Otwórz kartę http/https, którą chcesz przekazać.", "err");
    return;
  }
  const profile = document.getElementById("profile").value;
  try {
    setStatus("Uruchamianie…");
    const response = await nativeMessage({cmd: "launch", action, url: currentUrl, profile});
    if (!response.ok) throw new Error(response.error || "Nie udało się uruchomić aplikacji");
    setStatus("Przekazano do aplikacji.", "ok");
  } catch (e) {
    setStatus("Błąd: " + e.message, "err");
  }
}

document.getElementById("open").addEventListener("click", () => launch("open"));
document.getElementById("login").addEventListener("click", () => launch("login"));
document.getElementById("scan").addEventListener("click", () => launch("discover"));
document.getElementById("run").addEventListener("click", () => launch("run"));

(async () => {
  await activeTab();
  await loadProfiles();
})();
