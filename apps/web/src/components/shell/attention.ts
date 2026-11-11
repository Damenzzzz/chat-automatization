"use client";

import { useEffect, useRef, useSyncExternalStore } from "react";

const KEY = "satushy:alerts";
const EVENT = "satushy:alerts";

export function alertsEnabled(): boolean {
  try {
    return window.localStorage.getItem(KEY) === "on";
  } catch {
    return false;
  }
}

export function setAlerts(on: boolean) {
  try {
    window.localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    return;
  }
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(notify: () => void) {
  window.addEventListener(EVENT, notify);
  return () => window.removeEventListener(EVENT, notify);
}

export function useAlertsEnabled(): boolean {
  return useSyncExternalStore(subscribe, alertsEnabled, () => false);
}

function beep() {
  const Context = window.AudioContext;
  if (!Context) return;
  const context = new Context();
  const tone = context.createOscillator();
  const gain = context.createGain();
  const now = context.currentTime;
  tone.frequency.value = 880;
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.15, now + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.35);
  tone.connect(gain).connect(context.destination);
  tone.start();
  tone.stop(now + 0.4);
  tone.onended = () => void context.close();
}

export function useAttention(waiting: number | undefined) {
  const previous = useRef<number | undefined>(undefined);

  useEffect(() => {
    const before = previous.current;
    previous.current = waiting;
    if (before === undefined || waiting === undefined || waiting <= before) return;
    if (!alertsEnabled()) return;
    beep();
    if (document.hidden && "Notification" in window && Notification.permission === "granted") {
      const note = new Notification("Покупатель ждёт ответа", {
        body: `Диалогов без ответа менеджера: ${waiting}`,
        tag: "satushy-waiting",
      });
      note.onclick = () => {
        window.focus();
        note.close();
      };
    }
  }, [waiting]);
}
