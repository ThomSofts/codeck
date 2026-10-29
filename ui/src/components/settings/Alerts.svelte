<script lang="ts">
  // Configurações → Notificações: para cada tipo de aviso, se sai na Central de Notificações (macOS) / Windows e qual
  // som toca — PR nova, release esperando, IA perguntando, IA em espera… O ▶ ouve o som antes de escolher.
  import { BellOff, BellRing, Play, Volume1, Volume2, VolumeX } from "@lucide/svelte";
  import { ALERT_GROUPS, alertOf, setAlert, type AlertKind } from "../../lib/alerts.svelte";
  import { isMac } from "../../lib/keys";
  import { prefs } from "../../lib/prefs.svelte";
  import { play, SOUNDS, type SoundId } from "../../lib/sounds";
  import { store } from "../../lib/store.svelte";
  import Switch from "../Switch.svelte";

  const OS = isMac() ? "macOS" : "Windows";
  const rules = $derived((store.s?.rules?.settings || null) as Record<string, any> | null);
  const vol = $derived(Number(prefs.get("alerts.volume")));
  const mute = $derived(!!prefs.get("alerts.mute"));
  const preview = (s: SoundId) => play(s, Math.max(vol, 0.15));

  function pickSound(kind: AlertKind, s: SoundId) {
    setAlert(kind, { sound: s });
    if (!mute) preview(s);
  }
  // tudo de uma vez: silenciar ou tirar do sistema os avisos de um grupo
  function allOs(items: { kind: AlertKind }[], on: boolean) { for (const x of items) setAlert(x.kind, { os: on }); }
</script>

<div class="master card">
  <div class="mrow">
    <span class="mi">{#if mute}<VolumeX size={17} />{:else if vol < 0.4}<Volume1 size={17} />{:else}<Volume2 size={17} />{/if}</span>
    <div class="mt"><b>Sons dos avisos</b><span class="small muted">Tocados pelo Codeck — um som por leva de avisos, o do mais importante.</span></div>
    <input class="vol" type="range" min="0" max="1" step="0.05" value={vol} disabled={mute} aria-label="Volume"
      oninput={(e) => prefs.set("alerts.volume", Number((e.target as HTMLInputElement).value))} onchange={() => preview("acorde")} />
    <Switch checked={!mute} onchange={(v) => prefs.set("alerts.mute", !v)} />
  </div>
</div>

{#each ALERT_GROUPS as g (g.label)}
  {@const allOn = g.items.every(x => alertOf(x.kind, rules).os)}
  <div class="gh">
    <span>{g.label}</span>
    <button class="btn sm ghost" onclick={() => allOs(g.items, !allOn)} title={allOn ? `Nenhum destes no ${OS}` : `Todos estes no ${OS}`}>
      {#if allOn}<BellOff size={13} /> Tirar todos do sistema{:else}<BellRing size={13} /> Todos no sistema{/if}
    </button>
  </div>
  <div class="card list">
    <div class="lh"><span></span><span>No {OS}</span><span>Som</span></div>
    {#each g.items as d (d.kind)}
      {@const cur = alertOf(d.kind, rules)}
      <div class="al" class:quiet={!cur.os && cur.sound === "none"}>
        <div class="txt"><b>{d.label}</b><span class="small muted">{d.desc}</span></div>
        <div class="os"><Switch checked={cur.os} onchange={(v) => setAlert(d.kind, { os: v })} /></div>
        <div class="snd">
          <select class="input sm" value={cur.sound} onchange={(e) => pickSound(d.kind, (e.target as HTMLSelectElement).value as SoundId)} aria-label={`Som — ${d.label}`}>
            {#each SOUNDS as s (s.id)}<option value={s.id} disabled={s.id === "system" && !cur.os}>{s.label}{s.id === d.sound ? " (padrão)" : ""}</option>{/each}
          </select>
          <button class="btn sm ghost icon" title="Ouvir" disabled={cur.sound === "none" || cur.sound === "system"} onclick={() => preview(cur.sound)}><Play size={12} /></button>
        </div>
      </div>
    {/each}
  </div>
{/each}
<p class="small muted foot">Clicar numa notificação do sistema abre o item. “Som do sistema” usa o som da própria notificação (só com ela ligada); os demais são do Codeck e respeitam o volume acima.</p>

<style>
  .card { border: 1px solid var(--line); border-radius: 12px; background: var(--surface); }
  .master { padding: 12px 14px; margin-bottom: 18px; }
  .mrow { display: flex; align-items: center; gap: 12px; }
  .mi { display: grid; place-items: center; width: 34px; height: 34px; border-radius: 10px; background: var(--surface-2); color: var(--text-2); flex: none; }
  .mt { display: grid; gap: 2px; flex: 1; min-width: 0; }
  .vol { width: 140px; accent-color: var(--accent); }
  .gh { display: flex; align-items: center; justify-content: space-between; margin: 16px 2px 6px; font: 650 11px/1 var(--font); text-transform: uppercase;
    letter-spacing: 0.07em; color: var(--muted); }
  .gh .btn { text-transform: none; letter-spacing: 0; font-weight: 500; }
  .list { overflow: hidden; }
  .lh, .al { display: grid; grid-template-columns: minmax(0, 1fr) 130px 210px; align-items: center; gap: 14px; padding: 0 14px; }
  .lh { height: 30px; font: 600 10.5px/1 var(--font); color: var(--faint); text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid var(--line); }
  .al { min-height: 58px; padding-top: 8px; padding-bottom: 8px; border-top: 1px solid var(--line); transition: opacity var(--t); }
  .lh + .al { border-top: 0; }
  .al.quiet .txt { opacity: 0.55; }
  .txt { display: grid; gap: 2px; min-width: 0; }
  .txt b { font-weight: 600; font-size: 13px; }
  .snd { display: flex; align-items: center; gap: 4px; }
  .snd select { flex: 1; min-width: 0; height: 28px; font-size: 12.5px; }
  .foot { margin: 14px 2px 0; }
  @container (max-width: 640px) { .lh { display: none; } .al { grid-template-columns: minmax(0, 1fr) auto; } .snd { grid-column: 1 / -1; } }
</style>
