import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "leaflet/dist/leaflet.css";
import { App } from "./App";
import "./styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Корневой элемент не найден");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
