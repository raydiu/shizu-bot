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
      name: "/music queue",
      label: "Queue",
      description: "Affiche les titres en attente, le volume, le repeat, le shuffle et l'autoplay.",
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

window.addEventListener("beforeunload", () => {
  window.cancelAnimationFrame(rafId);
});

renderCommands();
bindCommandTabs();
bindNavigation();
bindInviteLinks();
bindRevealAnimation();
startManaField();
