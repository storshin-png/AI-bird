import { useState } from "react";
import { LoginStub } from "./screens/LoginStub";
import { MapShell } from "./screens/MapShell";

export function App() {
  const [entered, setEntered] = useState(false);

  if (!entered) {
    return <LoginStub onEnter={() => setEntered(true)} />;
  }

  return <MapShell onLeave={() => setEntered(false)} />;
}
