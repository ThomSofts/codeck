import { prefs } from "./prefs.svelte";

// Densidade da interface: "compact" encolhe alturas e espaçamentos (styles/app.css → [data-density="compact"]).
export type Density = "comfortable" | "compact";

/** Aplica a densidade no documento. Sem argumento, usa a preferência gravada. */
export function applyDensity(v?: Density) {
  const d = v ?? prefs.get("ui.density");
  if (d === "compact") document.documentElement.dataset.density = "compact";
  else delete document.documentElement.dataset.density;
}
