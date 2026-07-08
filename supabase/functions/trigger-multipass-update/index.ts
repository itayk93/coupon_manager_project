import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

serve(async (req) => {
    if (req.method === "OPTIONS") {
        return new Response("ok", { headers: corsHeaders });
    }

    try {
        const appBaseUrl = Deno.env.get("APP_BASE_URL") || "https://www.couponmasteril.com";
        const cronToken = Deno.env.get("CRON_API_TOKEN");

        if (!cronToken) {
            throw new Error("CRON_API_TOKEN not configured");
        }

        const endpoint = new URL("/api/cron/update_multipass", appBaseUrl);
        endpoint.searchParams.set("mode", "full");

        console.log(`Triggering Multipass full update via ${endpoint.toString()}`);

        const response = await fetch(endpoint.toString(), {
            method: "POST",
            headers: {
                "X-Cron-Secret": cronToken,
                "Content-Type": "application/json",
            },
        });

        const responseText = await response.text();
        let responseBody: unknown = responseText;
        try {
            responseBody = JSON.parse(responseText);
        } catch (_) {
            // Keep non-JSON responses as text for diagnostics.
        }

        if (!response.ok) {
            console.error("Flask cron endpoint error:", response.status, responseText);
            throw new Error(`Flask cron endpoint failed: ${response.status} ${responseText}`);
        }

        return new Response(JSON.stringify({
            success: true,
            message: "Multipass full update triggered",
            endpoint: endpoint.toString(),
            upstreamStatus: response.status,
            upstreamResponse: responseBody,
        }), {
            headers: { ...corsHeaders, "Content-Type": "application/json" },
            status: 200,
        });

    } catch (error: unknown) {
        console.error("Function error:", error);
        const message = error instanceof Error ? error.message : "Unknown error";
        return new Response(JSON.stringify({ error: message }), {
            headers: { ...corsHeaders, "Content-Type": "application/json" },
            status: 400,
        });
    }
});
