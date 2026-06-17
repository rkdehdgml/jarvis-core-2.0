import { useEffect, useRef, useState } from "react";

/**
 * active가 true인 동안 마이크 입력 음량을 실시간으로 샘플링해
 * barCount개의 0~1 정규화 값 배열로 반환한다.
 *
 * 마이크 권한이 없거나 획득에 실패하면 빈 배열을 반환한다. 호출 측은
 * 빈 배열일 때 기존 CSS 애니메이션으로 자연스럽게 대체해야 한다.
 */
export function useMicLevels(active: boolean, barCount: number): number[] {
  const [levels, setLevels] = useState<number[]>([]);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    if (!active) {
      setLevels([]);
      return;
    }

    let stream: MediaStream | null = null;
    let audioCtx: AudioContext | null = null;
    let cancelled = false;

    const start = async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }

        audioCtx = new AudioContext();
        const source = audioCtx.createMediaStreamSource(stream);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);

        const data = new Uint8Array(analyser.frequencyBinCount);
        const chunkSize = Math.max(1, Math.floor(data.length / barCount));

        const tick = () => {
          analyser.getByteFrequencyData(data);
          const next: number[] = [];
          for (let i = 0; i < barCount; i++) {
            const start = i * chunkSize;
            const end = Math.min(start + chunkSize, data.length);
            let sum = 0;
            for (let j = start; j < end; j++) sum += data[j];
            next.push(end > start ? sum / (end - start) / 255 : 0);
          }
          setLevels(next);
          frameRef.current = requestAnimationFrame(tick);
        };
        tick();
      } catch {
        // 마이크 권한 없음/실패 — 빈 배열을 유지해 호출 측이 기존 애니메이션을 쓰게 한다.
        setLevels([]);
      }
    };

    start();

    return () => {
      cancelled = true;
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      audioCtx?.close();
      stream?.getTracks().forEach((track) => track.stop());
    };
  }, [active, barCount]);

  return levels;
}
