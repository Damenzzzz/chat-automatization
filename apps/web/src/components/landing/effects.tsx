"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
  type ReactNode,
} from "react";

import { cn } from "@/lib/utils";

function reducedMotion(): boolean {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

type Star = { x: number; y: number; r: number; base: number; speed: number; phase: number };
type Meteor = { x: number; y: number; life: number };

export function Starfield({ className }: { className?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const element = canvas.current;
    const context = element?.getContext("2d");
    if (!element || !context) return;
    const still = reducedMotion();
    let stars: Star[] = [];
    let meteor: Meteor | null = null;
    let frame = 0;
    let pointerX = 0;
    let pointerY = 0;
    let width = 0;
    let height = 0;

    const resize = () => {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = element.clientWidth;
      height = element.clientHeight;
      element.width = width * ratio;
      element.height = height * ratio;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      const count = Math.round((width * height) / 3200);
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * width,
        y: Math.random() * height,
        r: Math.random() * 1.3 + 0.2,
        base: Math.random() * 0.6 + 0.2,
        speed: Math.random() * 0.002 + 0.0005,
        phase: Math.random() * Math.PI * 2,
      }));
    };

    const draw = (time: number) => {
      context.clearRect(0, 0, width, height);
      const shiftX = (pointerX - 0.5) * 14;
      const shiftY = (pointerY - 0.5) * 10;
      for (const star of stars) {
        const twinkle = still ? 1 : 0.6 + 0.4 * Math.sin(time * star.speed + star.phase);
        const depth = star.r / 1.5;
        context.globalAlpha = star.base * twinkle;
        context.fillStyle = star.r > 1.2 ? "#ffe6a3" : "#d8f6ff";
        context.beginPath();
        context.arc(star.x + shiftX * depth, star.y + shiftY * depth, star.r, 0, Math.PI * 2);
        context.fill();
      }
      if (!still) {
        if (!meteor && Math.random() < 0.004) {
          meteor = {
            x: Math.random() * width * 0.7 + width * 0.2,
            y: Math.random() * height * 0.3,
            life: 1,
          };
        }
        if (meteor) {
          const length = 120;
          const gradient = context.createLinearGradient(
            meteor.x,
            meteor.y,
            meteor.x + length,
            meteor.y - length * 0.45,
          );
          gradient.addColorStop(0, "rgba(255,255,255,0.9)");
          gradient.addColorStop(1, "rgba(61,224,245,0)");
          context.globalAlpha = meteor.life;
          context.strokeStyle = gradient;
          context.lineWidth = 1.4;
          context.beginPath();
          context.moveTo(meteor.x, meteor.y);
          context.lineTo(meteor.x + length, meteor.y - length * 0.45);
          context.stroke();
          meteor.x -= 9;
          meteor.y += 4;
          meteor.life -= 0.02;
          if (meteor.life <= 0) meteor = null;
        }
        frame = requestAnimationFrame(draw);
      }
      context.globalAlpha = 1;
    };

    const onPointer = (event: globalThis.PointerEvent) => {
      pointerX = event.clientX / window.innerWidth;
      pointerY = event.clientY / window.innerHeight;
      if (still) draw(0);
    };

    resize();
    frame = requestAnimationFrame(draw);
    window.addEventListener("resize", resize);
    window.addEventListener("pointermove", onPointer, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onPointer);
    };
  }, []);

  return <canvas ref={canvas} aria-hidden className={cn("pointer-events-none", className)} />;
}

export function Reveal({
  children,
  delay = 0,
  className,
  as: Tag = "div",
}: {
  children: ReactNode;
  delay?: number;
  className?: string;
  as?: "div" | "li" | "section";
}) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          element.dataset.reveal = "shown";
          observer.disconnect();
        }
      },
      { rootMargin: "0px 0px -10% 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return (
    <Tag
      ref={ref as never}
      data-reveal=""
      style={{ "--delay": `${delay}ms` } as CSSProperties}
      className={className}
    >
      {children}
    </Tag>
  );
}

export function SpotlightGroup({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  function move(event: PointerEvent<HTMLDivElement>) {
    for (const card of event.currentTarget.querySelectorAll<HTMLElement>("[data-spotlight]")) {
      const box = card.getBoundingClientRect();
      card.style.setProperty("--x", `${event.clientX - box.left}px`);
      card.style.setProperty("--y", `${event.clientY - box.top}px`);
    }
  }
  return (
    <div onPointerMove={move} className={className}>
      {children}
    </div>
  );
}

export function Tilt({ children, className }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  function move(event: PointerEvent<HTMLDivElement>) {
    const element = ref.current;
    if (!element || event.pointerType !== "mouse" || reducedMotion()) return;
    const box = element.getBoundingClientRect();
    const x = (event.clientX - box.left) / box.width - 0.5;
    const y = (event.clientY - box.top) / box.height - 0.5;
    element.style.transform = `perspective(1200px) rotateY(${x * 6}deg) rotateX(${-y * 6}deg)`;
  }
  function leave() {
    if (ref.current) ref.current.style.transform = "";
  }
  return (
    <div
      ref={ref}
      onPointerMove={move}
      onPointerLeave={leave}
      className={cn("transition-transform duration-300 ease-out will-change-transform", className)}
    >
      {children}
    </div>
  );
}

export function RotatingWords({
  words,
  className,
  boxClassName,
}: {
  words: string[];
  className?: string;
  boxClassName?: string;
}) {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (reducedMotion()) return;
    const timer = setInterval(() => setIndex((value) => (value + 1) % words.length), 2600);
    return () => clearInterval(timer);
  }, [words.length]);
  return (
    <span className={cn("relative inline-block", boxClassName)}>
      <span className="sr-only">{words.join(", ")}</span>
      <span key={index} aria-hidden className={cn("inline-block animate-word", className)}>
        {words[index]}
      </span>
    </span>
  );
}

export function StickyNav({ children }: { children: ReactNode }) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <div
      className={cn(
        "fixed inset-x-0 top-0 z-40 transition-[background-color,border-color,backdrop-filter] duration-300",
        scrolled
          ? "border-b border-white/10 bg-night/70 backdrop-blur-xl"
          : "border-b border-transparent",
      )}
    >
      {children}
    </div>
  );
}
