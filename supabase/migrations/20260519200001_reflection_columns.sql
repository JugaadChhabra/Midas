alter table audit_configs
    add column if not exists niche_queries    jsonb,
    add column if not exists reflection_mode text default 'shadow';

alter table audits
    add column if not exists prompt_version_id bigint references prompt_versions(id);
