import { useState } from "react";

import { JarvisFull } from "./components/JarvisFull";
import { JarvisMinimal } from "./components/JarvisMinimal";

/**
 * 풀/미니멀 모드 전환은 본체와 무관한 순수 화면 상태다.
 * 두 컴포넌트 모두 useJarvisStatus() 를 동일하게 구독하고 배치만 다르다.
 */
export function App() {
  const [fullMode, setFullMode] = useState(true);

  return (
    <div className="app-shell">
      <div className="mode-switch-bar">
        <button
          type="button"
          className="mode-switch"
          onClick={() => setFullMode((v) => !v)}
        >
          {fullMode ? "미니멀 모드" : "풀 모드"}
        </button>
      </div>
      {fullMode ? <JarvisFull /> : <JarvisMinimal />}
    </div>
  );
}
