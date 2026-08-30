import * as PIXI from "pixi.js";
import * as pixiUnsafeEval from "@pixi/unsafe-eval";

// Pixi 6 generates uniform-sync functions with `new Function` by default.
// The official compatibility package replaces that path with static setters,
// so the player can keep a strict CSP without allowing unsafe-eval.
pixiUnsafeEval.install(PIXI);

window.PIXI = PIXI;

const { Live2DModel } = require("pixi-live2d-display/cubism4");

const canvas = document.getElementById("live2d-canvas");
const status = document.getElementById("status");
const motionBar = document.getElementById("motion-bar");
document.getElementById("close-player").addEventListener("click", async () => {
  if (window.pywebview?.api?.close_player) {
    await window.pywebview.api.close_player();
  } else {
    window.close();
  }
});

function setStatus(message, error = false) {
  status.textContent = message;
  status.classList.toggle("error", error);
}

async function boot() {
  const response = await fetch("/config.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`配置读取失败：HTTP ${response.status}`);
  const config = await response.json();
  document.title = `LabCapsule Live2D · ${config.name}`;

  const app = new PIXI.Application({
    view: canvas,
    resizeTo: window,
    backgroundAlpha: 0,
    antialias: true,
    autoDensity: true,
    resolution: Math.min(window.devicePixelRatio || 1, 2),
  });
  const model = await Live2DModel.from(config.modelUrl, { autoInteract: true });
  app.stage.addChild(model);
  model.anchor.set(0.5, 0.5);
  model.interactive = true;

  function fitModel() {
    model.scale.set(1);
    const chromeHeight = config.mode === "overlay" ? 20 : 92;
    const usableHeight = Math.max(200, window.innerHeight - chromeHeight);
    const factor = Math.min(
      (window.innerWidth * 0.92) / Math.max(1, model.width),
      (usableHeight * 0.94) / Math.max(1, model.height),
    );
    model.scale.set(factor);
    model.position.set(window.innerWidth / 2, chromeHeight + usableHeight / 2);
  }

  fitModel();
  window.addEventListener("resize", fitModel);
  model.on("hit", (areas) => {
    const preferred = areas.includes("Body") ? "Tap@Body" : "Tap";
    const group = config.motionGroups.includes(preferred)
      ? preferred
      : config.motionGroups.find((name) => name !== "Idle");
    if (group) model.motion(group);
  });

  for (const group of config.motionGroups) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = group;
    button.addEventListener("click", () => model.motion(group));
    motionBar.appendChild(button);
  }
  if (config.mode === "overlay") {
    document.documentElement.classList.add("overlay");
    document.body.classList.add("overlay");
  }
  setStatus(`${config.name} · ${config.motionCount} 个动作 · WebGL 就绪`);
}

boot().catch((error) => {
  setStatus(`Live2D 启动失败：${error?.message || error}`, true);
});
