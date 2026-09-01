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
  let config = window.LABCAPSULE_CONFIG;
  if (!config) {
    const response = await fetch("/config.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`配置读取失败：HTTP ${response.status}`);
    config = await response.json();
  }
  document.title = `LabCapsule Live2D · ${config.name}`;

  const app = new PIXI.Application({
    view: canvas,
    resizeTo: window,
    backgroundAlpha: 0,
    antialias: true,
    autoDensity: true,
    resolution: Math.min(window.devicePixelRatio || 1, 2),
    preserveDrawingBuffer: Boolean(config.capture),
  });
  const model = await Live2DModel.from(config.modelUrl, { autoInteract: true });
  app.stage.addChild(model);
  model.anchor.set(0.5, 0.5);
  model.interactive = true;

  function fitModel() {
    model.scale.set(1);
    const chromeHeight = config.capture ? 0 : (config.mode === "overlay" ? 20 : 92);
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
  if (config.capture) {
    document.documentElement.classList.add("capture");
    document.body.classList.add("capture");
  }
  setStatus(`${config.name} · ${config.motionCount} 个动作 · WebGL 就绪`);

  let controlRevision = 0;
  const pickMotionGroup = (action) => {
    const preferences = {
      BOUNCE: ["FlickUp", "Tap@Body", "Tap"],
      TILT: ["Flick", "Tap@Head", "Tap"],
      THINK: ["Tap@Head", "Idle"],
      TALK: ["Tap@Body", "Tap", "Flick"],
      SCAN: ["FlickUp", "Tap@Body", "Tap"],
      CELEBRATE: ["FlickUp", "Tap@Body", "Tap"],
      ALERT: ["FlickDown", "Flick", "Tap"],
      SLEEP: ["Idle"],
      IDLE: ["Idle"],
    };
    return (preferences[action] || preferences.TALK)
      .find((group) => config.motionGroups.includes(group))
      || config.motionGroups.find((group) => group !== "Idle")
      || config.motionGroups[0];
  };
  window.labcapsulePetAction = (emotion, action) => {
    const group = pickMotionGroup(String(action || "TALK").toUpperCase());
    if (group) model.motion(group);
    setStatus(`${config.name} · ${emotion || "SPEAKING"} · ${group || "IDLE"}`);
  };
  const pollControl = async () => {
    if (!config.controlUrl) return;
    try {
      const current = await fetch(config.controlUrl, { cache: "no-store" }).then((item) => item.json());
      if (Number.isFinite(current.revision) && current.revision > controlRevision) {
        controlRevision = current.revision;
        const group = pickMotionGroup(String(current.action || "TALK").toUpperCase());
        if (group) model.motion(group);
        setStatus(`${config.name} · ${current.emotion || "SPEAKING"} · ${group || "IDLE"}`);
      }
    } catch (_error) {
      // The main app may be exiting or atomically replacing the tiny control file.
    }
  };
  if (config.controlUrl) window.setInterval(pollControl, 300);

  if (config.capture) {
    const wait = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));
    const idleGroup = config.motionGroups.includes("Idle") ? "Idle" : config.motionGroups[0];
    if (idleGroup) model.motion(idleGroup);
    await wait(700);
    for (let index = 0; index < config.captureFrames; index += 1) {
      await wait(config.captureIntervalMs);
      app.render();
      const dataUrl = canvas.toDataURL("image/png");
      const saved = await window.pywebview?.api?.save_capture_frame(
        dataUrl, index, config.captureIntervalMs,
      );
      if (!saved) throw new Error(`设备代理第 ${index + 1} 帧保存失败`);
    }
    const complete = await window.pywebview?.api?.complete_capture(
      config.captureFrames, config.captureIntervalMs,
    );
    if (!complete) throw new Error("设备代理收尾失败");
  }
}

boot().catch((error) => {
  setStatus(`Live2D 启动失败：${error?.message || error}`, true);
});
