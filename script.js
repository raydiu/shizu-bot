const BOT_CLIENT_ID = "TON_CLIENT_ID";
const SUPPORT_SERVER_URL = "#";

const commands = {
  moderation: [
    {
      name: "/shield",
      label: "Anti-Raid",
      description: "Active une protection temporaire avec verrouillage, logs et surveillance des arrivées.",
    },
    {
      name: "/warn",
      label: "Sanction",
      description: "Ajoute un avertissement propre avec raison, modérateur et historique du membre.",
    },
    {
      name: "/mute",
      label: "Silence",
      description: "Coupe l'accès vocal ou textuel d'un membre pendant une durée précise.",
    },
    {
      name: "/ticket",
      label: "Support",
      description: "Ouvre un salon privé pour gérer les demandes importantes sans chaos.",
    },
  ],
  anime: [
    {
      name: "/anime",
      label: "Recherche",
      description: "Affiche une fiche stylée pour découvrir un anime, ses infos et son ambiance.",
    },
    {
      name: "/hug",
      label: "Social",
      description: "Envoie une interaction anime chaleureuse avec une réponse visuelle.",
    },
    {
      name: "/duel",
      label: "Mini-jeu",
      description: "Lance un duel fun entre deux membres avec un résultat façon scène d'action.",
    },
    {
      name: "/quote",
      label: "Lore",
      description: "Génère une citation anime ou fantasy pour donner du style au chat.",
    },
  ],
  utility: [
    {
      name: "/setup",
      label: "Core",
      description: "Configure les salons, rôles, logs et modules importants du serveur.",
    },
    {
      name: "/profile",
      label: "Membre",
      description: "Affiche une carte utilisateur avec niveau, activité et badges.",
    },
    {
      name: "/server",
      label: "Info",
      description: "Montre les statistiques principales du serveur dans un panneau lisible.",
    },
    {
      name: "/ping",
      label: "Status",
      description: "Vérifie la latence du bot et l'état du système en temps réel.",
    },
  ],
};

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const canvas = document.querySelector("#mana-field");
const ctx = canvas.getContext("2d");
const tabs = document.querySelectorAll(".command-tab");
const commandList = document.querySelector("#command-list");
const navToggle = document.querySelector(".nav-toggle");
const nav = document.querySelector(".site-nav");
const inviteLinks = document.querySelectorAll(".invite-link");
const supportLinks = document.querySelectorAll('a[aria-label="Rejoindre le support Discord"]');

let particles = [];
let width = 0;
let height = 0;
let rafId = 0;

function setIconLibrary() {
  if (window.lucide) {
    window.lucide.createIcons();
  }
}

function renderCommands(category = "moderation") {
  const items = commands[category] || commands.moderation;
  commandList.innerHTML = items
    .map(
      (command) => `
        <article class="command-item">
          <div class="command-name">${command.name}</div>
          <p>${command.description}</p>
          <span class="command-badge">${command.label}</span>
        </article>
      `
    )
    .join("");
}

function bindCommandTabs() {
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((item) => {
        item.classList.remove("active");
        item.setAttribute("aria-selected", "false");
      });

      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      renderCommands(tab.dataset.category);
    });
  });
}

function bindNavigation() {
  navToggle.addEventListener("click", () => {
    const isOpen = nav.classList.toggle("open");
    navToggle.setAttribute("aria-expanded", String(isOpen));
  });

  nav.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      nav.classList.remove("open");
      navToggle.setAttribute("aria-expanded", "false");
    });
  });
}

function bindExternalLinks() {
  const hasClientId = BOT_CLIENT_ID && BOT_CLIENT_ID !== "TON_CLIENT_ID";
  const inviteUrl = `https://discord.com/oauth2/authorize?client_id=${BOT_CLIENT_ID}&permissions=8&scope=bot%20applications.commands`;

  inviteLinks.forEach((link) => {
    link.href = hasClientId ? inviteUrl : "#invite";
    link.addEventListener("click", (event) => {
      if (!hasClientId) {
        event.preventDefault();
        showPulseMessage("Ajoute l'ID client Discord dans script.js pour activer l'invitation.");
      }
    });
  });

  supportLinks.forEach((link) => {
    link.href = SUPPORT_SERVER_URL;
    link.addEventListener("click", (event) => {
      if (!SUPPORT_SERVER_URL || SUPPORT_SERVER_URL === "#") {
        event.preventDefault();
        showPulseMessage("Ajoute ton lien de serveur support dans script.js.");
      }
    });
  });
}

function showPulseMessage(message) {
  const toast = document.createElement("div");
  toast.className = "system-toast";
  toast.textContent = message;
  document.body.appendChild(toast);

  window.setTimeout(() => toast.classList.add("visible"), 20);
  window.setTimeout(() => {
    toast.classList.remove("visible");
    window.setTimeout(() => toast.remove(), 260);
  }, 3200);
}

function bindRevealAnimation() {
  const revealItems = document.querySelectorAll("[data-reveal]");
  document.body.classList.add("reveal-ready");

  if (!("IntersectionObserver" in window)) {
    revealItems.forEach((item) => item.classList.add("visible"));
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("visible");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.18 }
  );

  revealItems.forEach((item) => observer.observe(item));
}

function resizeCanvas() {
  width = window.innerWidth;
  height = window.innerHeight;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  createParticles();
}

function createParticles() {
  const count = Math.min(110, Math.floor((width * height) / 13500));
  particles = Array.from({ length: count }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    size: Math.random() * 2.2 + 0.7,
    speedX: (Math.random() - 0.5) * 0.32,
    speedY: Math.random() * -0.45 - 0.08,
    hue: Math.random() > 0.72 ? 48 : Math.random() > 0.42 ? 188 : 260,
    alpha: Math.random() * 0.52 + 0.18,
  }));
}

function drawManaField() {
  ctx.clearRect(0, 0, width, height);

  particles.forEach((particle, index) => {
    particle.x += particle.speedX;
    particle.y += particle.speedY;

    if (particle.y < -12) particle.y = height + 12;
    if (particle.x < -12) particle.x = width + 12;
    if (particle.x > width + 12) particle.x = -12;

    ctx.beginPath();
    ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
    ctx.fillStyle = `hsla(${particle.hue}, 100%, 72%, ${particle.alpha})`;
    ctx.shadowBlur = 18;
    ctx.shadowColor = `hsla(${particle.hue}, 100%, 70%, 0.9)`;
    ctx.fill();
    ctx.shadowBlur = 0;

    for (let next = index + 1; next < particles.length; next += 1) {
      const other = particles[next];
      const distance = Math.hypot(particle.x - other.x, particle.y - other.y);

      if (distance < 96) {
        ctx.beginPath();
        ctx.moveTo(particle.x, particle.y);
        ctx.lineTo(other.x, other.y);
        ctx.strokeStyle = `rgba(101, 239, 255, ${0.11 - distance / 1200})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }
  });

  rafId = window.requestAnimationFrame(drawManaField);
}

function startManaField() {
  if (reducedMotion) {
    canvas.remove();
    return;
  }

  resizeCanvas();
  drawManaField();
  window.addEventListener("resize", resizeCanvas);
}

window.addEventListener("beforeunload", () => {
  window.cancelAnimationFrame(rafId);
});

setIconLibrary();
renderCommands();
bindCommandTabs();
bindNavigation();
bindExternalLinks();
bindRevealAnimation();
startManaField();
