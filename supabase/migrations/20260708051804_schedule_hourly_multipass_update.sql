-- Schedule the Multipass update orchestrator to run every hour.
--
-- Required Vault secrets:
--   multipass_update_function_url = https://<project-ref>.supabase.co/functions/v1/trigger-multipass-update
--   supabase_anon_key             = <project anon key>
--
-- Required Edge Function secrets:
--   APP_BASE_URL=https://www.couponmasteril.com
--   CRON_API_TOKEN=<same token configured in Flask production>

create extension if not exists pg_cron with schema extensions;
create extension if not exists pg_net with schema extensions;
create extension if not exists supabase_vault with schema vault;

create or replace function public.trigger_hourly_multipass_update()
returns void
language plpgsql
security definer
set search_path = public, extensions, vault
as $$
declare
  function_url text;
  anon_key text;
begin
  select decrypted_secret
    into function_url
    from vault.decrypted_secrets
   where name = 'multipass_update_function_url'
   limit 1;

  select decrypted_secret
    into anon_key
    from vault.decrypted_secrets
   where name = 'supabase_anon_key'
   limit 1;

  if function_url is null or function_url = '' then
    raise exception 'Missing Vault secret: multipass_update_function_url';
  end if;

  if anon_key is null or anon_key = '' then
    raise exception 'Missing Vault secret: supabase_anon_key';
  end if;

  perform net.http_post(
    url := function_url,
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || anon_key,
      'apikey', anon_key,
      'Content-Type', 'application/json'
    ),
    body := '{}'::jsonb,
    timeout_milliseconds := 5000
  );
end;
$$;

do $$
begin
  perform cron.unschedule('hourly-multipass-update');
exception
  when others then
    null;
end;
$$;

select cron.schedule(
  'hourly-multipass-update',
  '0 * * * *',
  $$select public.trigger_hourly_multipass_update();$$
);
