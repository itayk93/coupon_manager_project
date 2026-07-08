-- Close Supabase advisor warning rls_disabled_in_public for operational tables.
-- These tables are managed by backend jobs/admin flows and should not be
-- readable or writable through the public Supabase API roles.

alter table public.auto_update_runs enable row level security;
alter table public.scheduled_tasks enable row level security;
alter table public.task_execution_logs enable row level security;

drop policy if exists "service_role_manage_auto_update_runs"
  on public.auto_update_runs;
create policy "service_role_manage_auto_update_runs"
  on public.auto_update_runs
  for all
  to service_role
  using (true)
  with check (true);

drop policy if exists "service_role_manage_scheduled_tasks"
  on public.scheduled_tasks;
create policy "service_role_manage_scheduled_tasks"
  on public.scheduled_tasks
  for all
  to service_role
  using (true)
  with check (true);

drop policy if exists "service_role_manage_task_execution_logs"
  on public.task_execution_logs;
create policy "service_role_manage_task_execution_logs"
  on public.task_execution_logs
  for all
  to service_role
  using (true)
  with check (true);
