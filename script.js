const INVITE_URL =
  "https://discord.com/oauth2/authorize?client_id=1499480527231516722&permissions=8&integration_type=0&scope=bot+applications.commands";

const commands = {
  music: [
    {
      name: "/music join",
      label: "Vocal",
      description: "Connecte Shizu Bot dans ton salon vocal pour préparer la session musique.",
    },
    {
      name: "/music play",
      label: "Play",
      description: "Joue une recherche ou un lien YouTube, Spotify ou Deezer avec une file d'attente.",
    },
    {
      name: "/music pause",
      label: "Pause",
      description: "Met la musique en pause.",
    },
    {
      name: "/music resume",
      label: "Resume",
      description: "Reprend la musique.",
    },
    {
      name: "/music skip",
      label: "Skip",
      description: "Passe à la musique suivante.",
    },
    {
      name: "/music voteskip",
      label: "Vote Skip",
      description: "Vote pour passer à la musique suivante.",
    },
    {
      name: "/music stop",
      label: "Stop",
      description: "Stoppe la musique et vide la file.",
    },
    {
      name: "/music leave",
      label: "Leave",
      description: "Déconnecte le bot du vocal.",
    },
    {
      name: "/music queue",
      label: "Queue",
      description: "Affiche la file d'attente.",
    },
    {
      name: "/music now",
      label: "Now",
      description: "Affiche le titre en cours.",
    },
    {
      name: "/music volume",
      label: "Volume",
      description: "Règle le volume entre 1 et 200.",
    },
    {
      name: "/music loop",
      label: "Loop",
      description: "Active ou désactive la répétition du titre.",
    },
    {
      name: "/music repeat",
      label: "Repeat",
      description: "Règle le mode repeat.",
    },
    {
      name: "/music autoplay",
      label: "Autoplay",
      description: "Active ou désactive l'autoplay.",
    },
    {
      name: "/music shuffle",
      label: "Shuffle",
      description: "Mélange la file et active/désactive le mode shuffle.",
    },
    {
      name: "/music lyrics",
      label: "Lyrics",
      description: "Affiche les paroles de la musique en cours ou d'une recherche.",
    },
  ],
  fun: [
    {
      name: "/duel",
      label: "Battle",
      description: "Défie un membre en duel fun avec résultat instantané.",
    },
    {
      name: "/ship",
      label: "Love",
      description: "Mesure la compatibilité entre deux membres avec une carte visuelle.",
    },
    {
      name: "/game trivia",
      label: "Quiz",
      description: "Lance un quiz rapide pour réveiller le chat.",
    },
    {
      name: "/game connect4",
      label: "Jeu",
      description: "Joue à puissance 4 contre un membre directement sur Discord.",
    },
    {
      name: "/mood",
      label: "GIF",
      description: "Affiche l'humeur d'un membre avec une réaction anime.",
    },
    {
      name: "/rp hug",
      label: "RP",
      description: "Lance une action RP avec GIF et compteur entre membres.",
    },
  ],
  anime: [
    {
      name: "/anime quote",
      label: "Quote",
      description: "Envoie une citation anime aléatoire dans un embed propre.",
    },
    {
      name: "/anime waifu",
      label: "Profil",
      description: "Génère un profil waifu ou husbando avec rareté et style.",
    },
    {
      name: "/rp hug",
      label: "RP",
      description: "Lance une action RP avec GIF et compteur entre membres.",
    },
    {
      name: "/mood",
      label: "GIF",
      description: "Affiche l'humeur d'un membre avec une réaction anime.",
    },
  ],
  economy: [
    {
      name: "/daily",
      label: "Cash",
      description: "Récupère une récompense quotidienne et augmente ta série.",
    },
    {
      name: "/mine",
      label: "Mine",
      description: "Trouve des minerais, puis revends-les avec /sellores.",
    },
    {
      name: "/shop",
      label: "Shop",
      description: "Ouvre la boutique du serveur avec objets, titres, badges et rôles.",
    },
    {
      name: "/rankcard",
      label: "Level",
      description: "Affiche une carte de rang visuelle avec XP et progression.",
    },
    {
      name: "/profile",
      label: "Profile",
      description: "Affiche ton profil économie complet.",
    },
    {
      name: "/rank",
      label: "Rank",
      description: "Affiche le rang niveau d'un membre.",
    },
    {
      name: "/rep",
      label: "Rep",
      description: "Donne 1 point de réputation à un membre.",
    },
  ],
  admin: [
    {
      name: "/setwelcome",
      label: "Welcome",
      description: "Définit le salon de bienvenue.",
    },
    {
      name: "/setlogs",
      label: "Logs",
      description: "Définit le salon de logs.",
    },
    {
      name: "/setannounce",
      label: "Announce",
      description: "Définit le salon d'annonce pour les events.",
    },
    {
      name: "/setlevelchannel",
      label: "Level Channel",
      description: "Définit le salon d'annonce des niveaux.",
    },
    {
      name: "/setstaffrole",
      label: "Staff Role",
      description: "Définit le rôle staff utilisé par le bot.",
    },
    {
      name: "/addshoprole",
      label: "Add Shop Role",
      description: "Ajoute un rôle achetable dans la boutique.",
    },
    {
      name: "/removeshoprole",
      label: "Remove Shop Role",
      description: "Retire un rôle de la boutique.",
    },
  ],
  utility: [
    {
      name: "/help",
      label: "Help",
      description: "Affiche l'aide du bot.",
    },
    {
      name: "/hub",
      label: "Hub",
      description: "Ouvre le centre d'animation du bot.",
    },
    {
      name: "/panel",
      label: "Panel",
      description: "Envoie le panneau d'animation dans un salon.",
    },
    {
      name: "/shoppanel",
      label: "Shop Panel",
      description: "Envoie un panneau boutique dans un salon.",
    },
    {
      name: "/confession",
      label: "Confession",
      description: "Partage un message anonyme avec boutons d'interaction.",
    },
    {
      name: "/event",
      label: "Event",
      description: "Crée un event avec boutons RSVP.",
    },
  ],
};

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const canvas = document.querySelector("#mana-field");
const ctx = canvas?.getContext("2d");
const tabs = document.querySelectorAll(".command-tab");
const commandList = document.querySelector("#command-list");
const navToggle = document.querySelector(".nav-toggle");
const nav = document.querySelector(".site-nav");
const inviteLinks = document.querySelectorAll(".invite-link");

let particles = [];
let width = 0;
let height = 0;
let rafId = 0;

function renderCommands(category = "music") {
  const items = commands[category] || commands.music;
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
  navToggle?.addEventListener("click", () => {
    const isOpen = nav.classList.toggle("open");
    navToggle.setAttribute("aria-expanded", String(isOpen));
  });

  nav?.querySelectorAll("a").forEach((link) => {
    link.addEventListener("click", () => {
      nav.classList.remove("open");
      navToggle?.setAttribute("aria-expanded", "false");
    });
  });
}

function bindInviteLinks() {
  inviteLinks.forEach((link) => {
    link.href = INVITE_URL;
    link.target = "_blank";
    link.rel = "noreferrer";
  });
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
    { threshold: 0.16 }
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
  const count = Math.min(120, Math.floor((width * height) / 12500));
  particles = Array.from({ length: count }, () => ({
    x: Math.random() * width,
    y: Math.random() * height,
    size: Math.random() * 2.4 + 0.7,
    speedX: (Math.random() - 0.5) * 0.34,
    speedY: Math.random() * -0.48 - 0.08,
    hue: Math.random() > 0.72 ? 278 : Math.random() > 0.38 ? 188 : 205,
    alpha: Math.random() * 0.58 + 0.18,
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
    ctx.shadowBlur = 20;
    ctx.shadowColor = `hsla(${particle.hue}, 100%, 70%, 0.95)`;
    ctx.fill();
    ctx.shadowBlur = 0;

    for (let next = index + 1; next < particles.length; next += 1) {
      const other = particles[next];
      const distance = Math.hypot(particle.x - other.x, particle.y - other.y);

      if (distance < 92) {
        ctx.beginPath();
        ctx.moveTo(particle.x, particle.y);
        ctx.lineTo(other.x, other.y);
        ctx.strokeStyle = `rgba(101, 239, 255, ${0.1 - distance / 1150})`;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }
  });

  rafId = window.requestAnimationFrame(drawManaField);
}

function startManaField() {
  if (!canvas || !ctx || reducedMotion) {
    canvas?.remove();
    return;
  }

  resizeCanvas();
  drawManaField();
  window.addEventListener("resize", resizeCanvas);
}

function renderHelpCommands(category = "music") {
  const items = commands[category] || commands.music;
  const helpList = document.querySelector("#help-list");
  helpList.innerHTML = items
    .map(
      (command) => `
        <article class="help-item">
          <div class="help-item-icon">
            <span class="ui-icon">${getCategoryIcon(category)}</span>
          </div>
          <div class="help-item-content">
            <strong class="help-item-name">${command.name}</strong>
            <span class="help-item-label">${command.label}</span>
            <p class="help-item-description">${command.description}</p>
          </div>
        </article>
      `
    )
    .join("");
}

function getCategoryIcon(category) {
  const icons = {
    music: "♪",
    fun: "🎮",
    anime: "✦",
    economy: "💰",
    admin: "⚙",
    utility: "🔧"
  };
  return icons[category] || "❓";
}

function bindHelpTabs() {
  const helpTabs = document.querySelectorAll(".help-tab");
  helpTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      helpTabs.forEach((item) => {
        item.classList.remove("active");
        item.setAttribute("aria-selected", "false");
      });

      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      renderHelpCommands(tab.dataset.category);
    });
  });
}

window.addEventListener("beforeunload", () => {
  window.cancelAnimationFrame(rafId);
});

renderCommands();
bindCommandTabs();
bindNavigation();
bindInviteLinks();
bindRevealAnimation();
renderHelpCommands();
bindHelpTabs();
bindHelpTabs();
startManaField();
