<script lang="ts">
  // "há 5 min" que anda sozinho (relógio da tela) e mostra a data e hora exatas ao passar o mouse.
  import { clock } from "../lib/clock.svelte";
  import { dateTime } from "../lib/format";

  let { iso, prefix = "" }: { iso?: string | null; prefix?: string } = $props();
</script>

<time datetime={iso || undefined} title={dateTime(iso)}>{prefix}{clock.ago(iso)}</time>
