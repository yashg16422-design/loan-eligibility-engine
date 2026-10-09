import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { adoptTokenFromUrl } from "./api/client";
import { App } from "./App";
import "./styles.css";

adoptTokenFromUrl(); // "View my matches" links from the email carry ?t=<token>

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
