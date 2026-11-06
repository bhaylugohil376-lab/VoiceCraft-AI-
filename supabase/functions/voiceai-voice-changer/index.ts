import "jsr:@supabase/functions-js/edge-runtime.d.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Cache-Control": "no-store",
};

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders, "Content-Type": "application/json" },
  });
}

Deno.serve(async (request: Request) => {
  if (request.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });
  if (request.method !== "GET" && request.method !== "POST") {
    return json(405, { success: false, error: "Method not allowed." });
  }

  const workerUrl = Deno.env.get("VOICE_CHANGER_WORKER_URL")?.replace(/\/$/, "");
  const workerToken = Deno.env.get("VOICE_CHANGER_WORKER_TOKEN");
  if (!workerUrl || !workerToken) {
    return json(503, {
      success: false,
      error: "Free CPU conversion server is not configured yet.",
    });
  }

  const incoming = new URL(request.url);
  const action = incoming.searchParams.get("action") || (request.method === "GET" ? "voices" : "convert");
  const headers = { Authorization: "Bearer " + workerToken };

  try {
    if (action === "voices" && request.method === "GET") {
      const response = await fetch(workerUrl + "/voices", { headers });
      const body = await response.text();
      return new Response(body, {
        status: response.status,
        headers: { ...corsHeaders, "Content-Type": response.headers.get("content-type") || "application/json" },
      });
    }

    if (action !== "convert" || request.method !== "POST") {
      return json(400, { success: false, error: "Unsupported voice-changer action." });
    }

    const form = await request.formData();
    const modelId = String(form.get("model_id") || "");
    const audio = form.get("audio");
    if (!modelId || !(audio instanceof File)) {
      return json(400, { success: false, error: "Select a voice model and upload an audio file." });
    }
    if (audio.size === 0 || audio.size > 20 * 1024 * 1024) {
      return json(413, { success: false, error: "Audio must be between 1 byte and 20 MB." });
    }

    const outgoing = new FormData();
    outgoing.set("audio", audio, audio.name || "recording.wav");
    const target = new URL(workerUrl + "/convert");
    target.searchParams.set("model_id", modelId);
    const response = await fetch(target, { method: "POST", headers, body: outgoing });
    if (!response.ok) {
      const detail = await response.text();
      return json(response.status, { success: false, error: detail.slice(0, 1800) || "CPU conversion failed." });
    }

    const responseHeaders = new Headers(corsHeaders);
    responseHeaders.set("Content-Type", response.headers.get("content-type") || "audio/wav");
    responseHeaders.set("Content-Disposition", 'attachment; filename="voicecraft-converted.wav"');
    return new Response(response.body, { status: 200, headers: responseHeaders });
  } catch (error) {
    return json(502, {
      success: false,
      error: error instanceof Error ? error.message : "Could not reach the CPU conversion server.",
    });
  }
});
