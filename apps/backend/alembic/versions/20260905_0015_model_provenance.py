"""Immutable model provenance and database-resolved committed-text context."""

from alembic import op

revision = "20260905_0015_model_provenance"
down_revision = "20260904_0014_sql_executions"
branch_labels = None
depends_on = None

# Frozen SQL, independent of runtime models and current protocol definitions.
FUNCTIONS = r"""
CREATE FUNCTION public.tamforge_provenance_canonical(j jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT SET search_path = pg_catalog AS $$
DECLARE result text;
BEGIN
 CASE jsonb_typeof(j)
 WHEN 'object' THEN
   SELECT '{' || coalesce(string_agg(to_jsonb(key)::text || ':' ||
     public.tamforge_provenance_canonical(value), ',' ORDER BY key COLLATE "C"), '') || '}'
     INTO result FROM jsonb_each(j);
 WHEN 'array' THEN
   SELECT '[' || coalesce(string_agg(public.tamforge_provenance_canonical(value), ','
     ORDER BY ordinal), '') || ']' INTO result FROM jsonb_array_elements(j)
     WITH ORDINALITY AS items(value, ordinal);
 WHEN 'number' THEN
   result := j::text;
   IF (result::numeric = 0) THEN RETURN '0'; END IF;
   IF position('.' in result) > 0 THEN result := rtrim(rtrim(result, '0'), '.'); END IF;
 ELSE result := j::text;
 END CASE;
 RETURN result;
END $$;
CREATE FUNCTION public.tamforge_provenance_keys(j jsonb, keys text[]) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_typeof(j) = 'object' AND j ?& keys AND j - keys = '{}'::jsonb, false)
$$;
CREATE FUNCTION public.tamforge_provenance_int(j jsonb, minimum bigint, maximum bigint)
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_typeof(j) = 'number' AND j::text ~ '^(0|[1-9][0-9]*)$'
   AND (j::text)::numeric BETWEEN minimum AND maximum, false)
$$;
CREATE FUNCTION public.tamforge_provenance_key(j jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_typeof(j) = 'string' AND j #>> '{}' ~
   '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$', false)
$$;
CREATE FUNCTION public.tamforge_provenance_hash(j jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
 SELECT coalesce(jsonb_typeof(j) = 'string' AND j #>> '{}' ~ '^[a-f0-9]{64}$', false)
$$;
CREATE FUNCTION public.tamforge_provenance_pin(j jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
 SELECT public.tamforge_provenance_keys(j, ARRAY['id','content_hash']) AND
   public.tamforge_provenance_int(j->'id',1,9223372036854775807) AND
   public.tamforge_provenance_hash(j->'content_hash')
$$;
CREATE FUNCTION public.tamforge_provenance_rubric(owner bigint, rubric bigint) RETURNS jsonb
LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
DECLARE r record; c record; entry jsonb; d record; item jsonb; n integer := 0;
BEGIN
 SELECT * INTO r FROM public.rubric_versions WHERE owner_id = owner AND id = rubric;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO c FROM public.config_seed_versions
   WHERE owner_id = owner AND id = r.config_seed_version_id;
 SELECT value INTO STRICT entry FROM jsonb_array_elements(c.canonical_payload->'rubrics'->'rubrics')
   WHERE value->>'slug' = r.rubric_key AND value->>'version' = r.version_key;
 IF entry->>'name' IS DISTINCT FROM r.name OR entry->>'scope' IS DISTINCT FROM r.scope_code
   OR (entry->>'scale_min')::numeric IS DISTINCT FROM r.scale_min
   OR (entry->>'scale_max')::numeric IS DISTINCT FROM r.scale_max THEN
   RAISE EXCEPTION 'invalid rubric provenance';
 END IF;
 FOR d IN SELECT * FROM public.rubric_dimensions WHERE owner_id = owner
   AND rubric_version_id = rubric ORDER BY ordinal LOOP
   item := entry->'dimensions'->n;
   IF d.ordinal <> n OR d.config_seed_version_id <> c.id
     OR item->>'slug' IS DISTINCT FROM d.dimension_key
     OR item->>'name' IS DISTINCT FROM d.name
     OR (item->>'weight')::numeric IS DISTINCT FROM d.weight
     OR (item->>'maximum')::numeric IS DISTINCT FROM d.max_score
     OR item->>'availability_rule' IS DISTINCT FROM d.availability_rule_code THEN
     RAISE EXCEPTION 'invalid rubric provenance';
   END IF;
   n := n + 1;
 END LOOP;
 IF n = 0 OR n <> jsonb_array_length(entry->'dimensions') THEN
   RAISE EXCEPTION 'invalid rubric provenance';
 END IF;
 RETURN jsonb_build_object('format',1,'kind','rubric_binding','owner_id',owner,
   'config_id',c.id,'config_hash',encode(c.content_hash,'hex'), 'rubric_id',r.id,
   'rubric_hash',encode(public.digest(convert_to(public.tamforge_provenance_canonical(entry),
   'UTF8'),'sha256'),'hex'), 'definition',entry);
END $$;
CREATE FUNCTION public.tamforge_provenance_context(owner bigint, activity bigint, item jsonb)
RETURNS boolean LANGUAGE plpgsql STABLE SET search_path = pg_catalog AS $$
DECLARE ref jsonb; a record; output jsonb; parts text[]; allowed text[]; selected jsonb;
 start_at integer; end_at integer;
BEGIN
 IF NOT public.tamforge_provenance_keys(item, ARRAY['format','kind','profile','owner_id',
   'activity_id','source_version','source_hash','ordinal','reason','reference','prepared_input_hash'])
   OR item->'format' <> '1'::jsonb OR item->>'kind' <> 'context'
   OR item->>'profile' <> 'committed-attempt-text-v1' OR item->'source_version' <> '1'::jsonb
   OR item->'owner_id' <> to_jsonb(owner) OR item->'activity_id' <> to_jsonb(activity)
   OR NOT public.tamforge_provenance_int(item->'ordinal',0,63)
   OR item->>'reason' NOT IN ('primary_evidence','supporting_evidence','comparison')
   OR NOT public.tamforge_provenance_hash(item->'source_hash')
   OR NOT public.tamforge_provenance_hash(item->'prepared_input_hash') THEN RETURN false; END IF;
 IF EXISTS(SELECT 1 FROM jsonb_each(item) WHERE value = 'null'::jsonb) THEN
   RETURN false; END IF;
 ref := item->'reference';
 IF EXISTS(SELECT 1 FROM jsonb_each(ref) WHERE value = 'null'::jsonb) THEN
   RETURN false; END IF;
 IF NOT public.tamforge_provenance_keys(ref, ARRAY['kind','attempt_id','commitment_sha256',
   'json_pointer','start_codepoint','end_codepoint']) OR ref->>'kind' <> 'attempt_text'
   OR NOT public.tamforge_provenance_int(ref->'attempt_id',1,9223372036854775807)
   OR NOT public.tamforge_provenance_hash(ref->'commitment_sha256')
   OR NOT public.tamforge_provenance_int(ref->'start_codepoint',0,16777216)
   OR NOT public.tamforge_provenance_int(ref->'end_codepoint',1,16777216)
   OR jsonb_typeof(ref->'json_pointer') <> 'string'
   OR length(ref->>'json_pointer') > 512 THEN RETURN false; END IF;
 SELECT * INTO a FROM public.attempts WHERE owner_id = owner AND activity_instance_id = activity
   AND id = (ref->>'attempt_id')::bigint;
 IF NOT FOUND OR a.original_text IS NULL OR encode(a.commitment_hash,'hex') <>
   ref->>'commitment_sha256' OR encode(public.digest(convert_to(a.original_text,'UTF8'),'sha256'),
   'hex') <> item->>'source_hash' THEN RETURN false; END IF;
 IF a.original_text::jsonb->'contract_version' IS DISTINCT FROM '1'::jsonb THEN
   RETURN false;
 END IF;
 output := a.original_text::jsonb->'output';
 allowed := CASE output->>'kind'
   WHEN 'reading' THEN ARRAY['key_ideas','boundary_or_failure','tam_customer_example',
                            'unresolved_question']
   WHEN 'sql' THEN ARRAY['query','result','validation','explanation','business_meaning']
   WHEN 'case' THEN ARRAY['discovery_questions','assumptions','working_notes','final_artifact',
                         'decisions','risks','unresolved_questions']
   WHEN 'writing' THEN ARRAY['draft_markdown','self_edit_notes']
   WHEN 'pipeline' THEN ARRAY['completed_action','artifact_summary','next_action']
   ELSE ARRAY[]::text[] END;
 parts := string_to_array(ref->>'json_pointer','/');
 IF array_length(parts,1) NOT IN (3,4) OR parts[1] <> '' OR parts[2] <> 'output'
   OR NOT parts[3] = ANY(allowed) THEN RETURN false; END IF;
 selected := output->parts[3];
 IF array_length(parts,1) = 4 THEN
   IF jsonb_typeof(selected) <> 'array' OR parts[4] !~ '^(0|[1-9][0-9]*)$'
     OR length(parts[4]) > 9 THEN RETURN false; END IF;
   selected := selected->(parts[4]::integer);
 END IF;
 start_at := (ref->>'start_codepoint')::integer;
 end_at := (ref->>'end_codepoint')::integer;
 IF jsonb_typeof(selected) IS DISTINCT FROM 'string' OR end_at <= start_at
   OR end_at > length(selected #>> '{}') THEN RETURN false; END IF;
 RETURN encode(public.digest(convert_to(substring(selected #>> '{}' FROM start_at+1
   FOR end_at-start_at),'UTF8'),'sha256'),'hex') = item->>'prepared_input_hash';
END $$;
"""

TABLES = r"""

CREATE TABLE prompt_versions (
    key TEXT NOT NULL,
    version TEXT NOT NULL,
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    owner_id BIGINT NOT NULL,
    canonical_json TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    hash_format INTEGER DEFAULT '1' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_prompt_versions PRIMARY KEY (id),
    CONSTRAINT uq_prompt_versions_owner_id_id UNIQUE (owner_id, id),
    CONSTRAINT ck_prompt_versions_id_positive CHECK (id > 0),
    CONSTRAINT ck_prompt_versions_owner_positive CHECK (owner_id > 0),
    CONSTRAINT ck_prompt_versions_hash_format_v1 CHECK (hash_format = 1),
    CONSTRAINT ck_prompt_versions_content_bounded CHECK (octet_length(canonical_json) BETWEEN 1
        AND 1048576),
    CONSTRAINT ck_prompt_versions_hash_matches CHECK (content_hash =
        public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')),
    CONSTRAINT uq_prompt_versions_key_version UNIQUE (owner_id, key, version),
    CONSTRAINT ck_prompt_versions_keys_safe CHECK (key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
        AND version ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT fk_prompt_versions_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id)
)

;

CREATE TABLE output_schema_versions (
    key TEXT NOT NULL,
    version TEXT NOT NULL,
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    owner_id BIGINT NOT NULL,
    canonical_json TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    hash_format INTEGER DEFAULT '1' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_output_schema_versions PRIMARY KEY (id),
    CONSTRAINT uq_output_schema_versions_owner_id_id UNIQUE (owner_id, id),
    CONSTRAINT ck_output_schema_versions_id_positive CHECK (id > 0),
    CONSTRAINT ck_output_schema_versions_owner_positive CHECK (owner_id > 0),
    CONSTRAINT ck_output_schema_versions_hash_format_v1 CHECK (hash_format = 1),
    CONSTRAINT ck_output_schema_versions_content_bounded CHECK (octet_length(canonical_json)
        BETWEEN 1 AND 1048576),
    CONSTRAINT ck_output_schema_versions_hash_matches CHECK (content_hash =
        public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')),
    CONSTRAINT ck_output_schema_versions_canonical_bytes CHECK (canonical_json =
        public.tamforge_provenance_canonical(canonical_json::jsonb)),
    CONSTRAINT uq_output_schema_versions_key_version UNIQUE (owner_id, key, version),
    CONSTRAINT ck_output_schema_versions_keys_safe CHECK (key ~
        '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$' AND version ~
        '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT ck_output_schema_versions_schema_identity CHECK
        (jsonb_typeof(canonical_json::jsonb) = 'object' AND canonical_json::jsonb->>'$id' = key
        IS TRUE),
    CONSTRAINT fk_output_schema_versions_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners
        (id)
)

;

CREATE TABLE rubric_version_hashes (
    config_id BIGINT GENERATED ALWAYS AS ((canonical_json::jsonb->>'config_id')::bigint) STORED
        NOT NULL,
    rubric_id BIGINT GENERATED ALWAYS AS ((canonical_json::jsonb->>'rubric_id')::bigint) STORED
        NOT NULL,
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    owner_id BIGINT NOT NULL,
    canonical_json TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    hash_format INTEGER DEFAULT '1' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_rubric_version_hashes PRIMARY KEY (id),
    CONSTRAINT uq_rubric_version_hashes_owner_id_id UNIQUE (owner_id, id),
    CONSTRAINT ck_rubric_version_hashes_id_positive CHECK (id > 0),
    CONSTRAINT ck_rubric_version_hashes_owner_positive CHECK (owner_id > 0),
    CONSTRAINT ck_rubric_version_hashes_hash_format_v1 CHECK (hash_format = 1),
    CONSTRAINT ck_rubric_version_hashes_content_bounded CHECK (octet_length(canonical_json)
        BETWEEN 1 AND 262144),
    CONSTRAINT ck_rubric_version_hashes_hash_matches CHECK (content_hash =
        public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')),
    CONSTRAINT ck_rubric_version_hashes_canonical_bytes CHECK (canonical_json =
        public.tamforge_provenance_canonical(canonical_json::jsonb)),
    CONSTRAINT uq_rubric_version_hashes_rubric UNIQUE (owner_id, rubric_id),
    CONSTRAINT fk_rubric_version_hashes_owner_id_rubric_versions FOREIGN KEY(owner_id,
        config_id, rubric_id) REFERENCES rubric_versions (owner_id, config_seed_version_id, id),
    CONSTRAINT fk_rubric_version_hashes_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners
        (id)
)

;

CREATE TABLE model_runs (
    invocation_key TEXT GENERATED ALWAYS AS (canonical_json::jsonb->>'invocation_key') STORED
        NOT NULL,
    activity_id BIGINT GENERATED ALWAYS AS ((canonical_json::jsonb->>'activity_id')::bigint)
        STORED NOT NULL,
    attempt_id BIGINT GENERATED ALWAYS AS ((canonical_json::jsonb->'attempt'->>'id')::bigint)
        STORED NOT NULL,
    prompt_id BIGINT GENERATED ALWAYS AS ((canonical_json::jsonb->'prompt'->>'id')::bigint)
        STORED NOT NULL,
    schema_id BIGINT GENERATED ALWAYS AS
        ((canonical_json::jsonb->'schema_version'->>'id')::bigint) STORED NOT NULL,
    rubric_binding_id BIGINT GENERATED ALWAYS AS
        ((canonical_json::jsonb->'rubric_binding'->>'id')::bigint) STORED NOT NULL,
    job_id BIGINT GENERATED ALWAYS AS ((canonical_json::jsonb->>'job_id')::bigint) STORED,
    predecessor_id BIGINT GENERATED ALWAYS AS
        ((canonical_json::jsonb->'predecessor'->>'id')::bigint) STORED,
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    owner_id BIGINT NOT NULL,
    canonical_json TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    hash_format INTEGER DEFAULT '1' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_model_runs PRIMARY KEY (id),
    CONSTRAINT uq_model_runs_owner_id_id UNIQUE (owner_id, id),
    CONSTRAINT ck_model_runs_id_positive CHECK (id > 0),
    CONSTRAINT ck_model_runs_owner_positive CHECK (owner_id > 0),
    CONSTRAINT ck_model_runs_hash_format_v1 CHECK (hash_format = 1),
    CONSTRAINT ck_model_runs_content_bounded CHECK (octet_length(canonical_json) BETWEEN 1 AND
        262144),
    CONSTRAINT ck_model_runs_hash_matches CHECK (content_hash =
        public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')),
    CONSTRAINT ck_model_runs_canonical_bytes CHECK (canonical_json =
        public.tamforge_provenance_canonical(canonical_json::jsonb)),
    CONSTRAINT uq_model_runs_invocation UNIQUE (owner_id, invocation_key),
    CONSTRAINT uq_model_runs_activity_id UNIQUE (owner_id, activity_id, id),
    CONSTRAINT fk_model_runs_attempt FOREIGN KEY(owner_id, activity_id, attempt_id) REFERENCES
        attempts (owner_id, activity_instance_id, id),
    CONSTRAINT fk_model_runs_prompt FOREIGN KEY(owner_id, prompt_id) REFERENCES prompt_versions
        (owner_id, id),
    CONSTRAINT fk_model_runs_schema FOREIGN KEY(owner_id, schema_id) REFERENCES
        output_schema_versions (owner_id, id),
    CONSTRAINT fk_model_runs_rubric FOREIGN KEY(owner_id, rubric_binding_id) REFERENCES
        rubric_version_hashes (owner_id, id),
    CONSTRAINT fk_model_runs_job FOREIGN KEY(owner_id, job_id) REFERENCES background_jobs
        (owner_id, id),
    CONSTRAINT fk_model_runs_predecessor FOREIGN KEY(owner_id, activity_id, predecessor_id)
        REFERENCES model_runs (owner_id, activity_id, id),
    CONSTRAINT fk_model_runs_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id)
)

;

CREATE TABLE model_run_context_items (
    ordinal INTEGER GENERATED ALWAYS AS ((canonical_json::jsonb->>'ordinal')::bigint) STORED NOT
        NULL,
    run_id BIGINT NOT NULL,
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    owner_id BIGINT NOT NULL,
    canonical_json TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    hash_format INTEGER DEFAULT '1' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_model_run_context_items PRIMARY KEY (id),
    CONSTRAINT uq_model_run_context_items_owner_id_id UNIQUE (owner_id, id),
    CONSTRAINT ck_model_run_context_items_id_positive CHECK (id > 0),
    CONSTRAINT ck_model_run_context_items_owner_positive CHECK (owner_id > 0),
    CONSTRAINT ck_model_run_context_items_hash_format_v1 CHECK (hash_format = 1),
    CONSTRAINT ck_model_run_context_items_content_bounded CHECK (octet_length(canonical_json)
        BETWEEN 1 AND 262144),
    CONSTRAINT ck_model_run_context_items_hash_matches CHECK (content_hash =
        public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')),
    CONSTRAINT ck_model_run_context_items_canonical_bytes CHECK (canonical_json =
        public.tamforge_provenance_canonical(canonical_json::jsonb)),
    CONSTRAINT fk_model_run_context_items_owner_id_model_runs FOREIGN KEY(owner_id, run_id)
        REFERENCES model_runs (owner_id, id),
    CONSTRAINT uq_model_run_context_items_run_id UNIQUE (run_id, ordinal),
    CONSTRAINT fk_model_run_context_items_owner_id_owners FOREIGN KEY(owner_id) REFERENCES
        owners (id)
)

;

CREATE TABLE model_run_events (
    sequence INTEGER GENERATED ALWAYS AS ((canonical_json::jsonb->>'sequence')::bigint) STORED
        NOT NULL,
    run_id BIGINT NOT NULL,
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    owner_id BIGINT NOT NULL,
    canonical_json TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    hash_format INTEGER DEFAULT '1' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_model_run_events PRIMARY KEY (id),
    CONSTRAINT uq_model_run_events_owner_id_id UNIQUE (owner_id, id),
    CONSTRAINT ck_model_run_events_id_positive CHECK (id > 0),
    CONSTRAINT ck_model_run_events_owner_positive CHECK (owner_id > 0),
    CONSTRAINT ck_model_run_events_hash_format_v1 CHECK (hash_format = 1),
    CONSTRAINT ck_model_run_events_content_bounded CHECK (octet_length(canonical_json) BETWEEN 1
        AND 262144),
    CONSTRAINT ck_model_run_events_hash_matches CHECK (content_hash =
        public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')),
    CONSTRAINT ck_model_run_events_canonical_bytes CHECK (canonical_json =
        public.tamforge_provenance_canonical(canonical_json::jsonb)),
    CONSTRAINT fk_model_run_events_owner_id_model_runs FOREIGN KEY(owner_id, run_id) REFERENCES
        model_runs (owner_id, id),
    CONSTRAINT uq_model_run_events_sequence UNIQUE (run_id, sequence),
    CONSTRAINT fk_model_run_events_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id)
)

;

CREATE TABLE agent_tool_calls (
    sequence INTEGER GENERATED ALWAYS AS ((canonical_json::jsonb->>'sequence')::bigint) STORED
        NOT NULL,
    call_key TEXT GENERATED ALWAYS AS (canonical_json::jsonb->'audit'->>'call_key') STORED NOT
        NULL,
    phase_slot INTEGER GENERATED ALWAYS AS (CASE WHEN canonical_json::jsonb->'audit'->>'phase' =
        'request' THEN 0 ELSE 1 END) STORED NOT NULL,
    run_id BIGINT NOT NULL,
    id BIGINT GENERATED ALWAYS AS IDENTITY,
    owner_id BIGINT NOT NULL,
    canonical_json TEXT NOT NULL,
    content_hash BYTEA NOT NULL,
    hash_format INTEGER DEFAULT '1' NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    CONSTRAINT pk_agent_tool_calls PRIMARY KEY (id),
    CONSTRAINT uq_agent_tool_calls_owner_id_id UNIQUE (owner_id, id),
    CONSTRAINT ck_agent_tool_calls_id_positive CHECK (id > 0),
    CONSTRAINT ck_agent_tool_calls_owner_positive CHECK (owner_id > 0),
    CONSTRAINT ck_agent_tool_calls_hash_format_v1 CHECK (hash_format = 1),
    CONSTRAINT ck_agent_tool_calls_content_bounded CHECK (octet_length(canonical_json) BETWEEN 1
        AND 16384),
    CONSTRAINT ck_agent_tool_calls_hash_matches CHECK (content_hash =
        public.digest(convert_to(canonical_json, 'UTF8'), 'sha256')),
    CONSTRAINT ck_agent_tool_calls_canonical_bytes CHECK (canonical_json =
        public.tamforge_provenance_canonical(canonical_json::jsonb)),
    CONSTRAINT fk_agent_tool_calls_owner_id_model_runs FOREIGN KEY(owner_id, run_id) REFERENCES
        model_runs (owner_id, id),
    CONSTRAINT uq_agent_tool_calls_sequence UNIQUE (run_id, sequence),
    CONSTRAINT uq_agent_tool_calls_call_phase UNIQUE (run_id, call_key, phase_slot),
    CONSTRAINT fk_agent_tool_calls_owner_id_owners FOREIGN KEY(owner_id) REFERENCES owners (id)
)

;
"""

GUARDS = r"""
CREATE FUNCTION public.tamforge_provenance_immutable() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN RAISE EXCEPTION 'model provenance is immutable'; END $$;

CREATE FUNCTION public.tamforge_provenance_insert() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE j jsonb; run record; a record; previous jsonb; seq integer; state text;
 e jsonb; t jsonb; request jsonb; n integer; pinned bytea; x jsonb; field text;
BEGIN
 j := NEW.canonical_json::jsonb;
 IF EXISTS(SELECT 1 FROM jsonb_each(j) WHERE value = 'null'::jsonb AND
   key NOT IN ('sdk_version','cli_version','job_id','predecessor')) THEN
   RAISE EXCEPTION 'invalid model provenance'; END IF;
 IF j->'format' IS DISTINCT FROM '1'::jsonb OR j->'owner_id' IS DISTINCT FROM to_jsonb(NEW.owner_id)
 THEN RAISE EXCEPTION 'invalid model provenance'; END IF;
 IF TG_TABLE_NAME = 'rubric_version_hashes' THEN
   IF j IS DISTINCT FROM public.tamforge_provenance_rubric(NEW.owner_id,
       (j->>'rubric_id')::bigint) THEN RAISE EXCEPTION 'invalid rubric provenance'; END IF;
 ELSIF TG_TABLE_NAME = 'model_runs' THEN
   IF NOT public.tamforge_provenance_keys(j, ARRAY['format','kind','owner_id','invocation_key',
     'activity_id','attempt','prompt','schema_version','rubric_binding','requested_model',
     'sdk_version','cli_version','job_id','predecessor','manifest','manifest_hash'])
     OR j->>'kind' <> 'run'
     OR NOT public.tamforge_provenance_int(j->'activity_id',1,9223372036854775807)
     OR NOT public.tamforge_provenance_key(j->'invocation_key')
     OR NOT public.tamforge_provenance_key(j->'requested_model')
     OR (j->'sdk_version' <> 'null'::jsonb AND NOT public.tamforge_provenance_key(j->'sdk_version'))
     OR (j->'cli_version' <> 'null'::jsonb AND NOT public.tamforge_provenance_key(j->'cli_version'))
     OR (j->'job_id' <> 'null'::jsonb AND NOT public.tamforge_provenance_int(j->'job_id',
       1,9223372036854775807))
     OR NOT public.tamforge_provenance_pin(j->'attempt')
     OR NOT public.tamforge_provenance_pin(j->'prompt')
     OR NOT public.tamforge_provenance_pin(j->'schema_version')
     OR NOT public.tamforge_provenance_pin(j->'rubric_binding')
     OR (j->'predecessor' <> 'null'::jsonb AND NOT public.tamforge_provenance_pin(j->'predecessor'))
     OR jsonb_typeof(j->'manifest') <> 'array'
     OR jsonb_array_length(j->'manifest') NOT BETWEEN 1 AND 64
     OR NOT public.tamforge_provenance_hash(j->'manifest_hash') THEN
     RAISE EXCEPTION 'invalid run provenance'; END IF;
   PERFORM 1 FROM public.activity_instances WHERE owner_id = NEW.owner_id
     AND id = (j->>'activity_id')::bigint FOR UPDATE;
   IF NOT FOUND THEN RAISE EXCEPTION 'invalid run provenance'; END IF;
   SELECT * INTO a FROM public.attempts WHERE owner_id = NEW.owner_id
     AND id = (j->'attempt'->>'id')::bigint
     AND activity_instance_id = (j->>'activity_id')::bigint;
   IF NOT FOUND OR encode(a.commitment_hash,'hex') <> j->'attempt'->>'content_hash' THEN
     RAISE EXCEPTION 'invalid run provenance'; END IF;
   SELECT content_hash INTO pinned FROM public.prompt_versions WHERE owner_id = NEW.owner_id
     AND id = (j->'prompt'->>'id')::bigint;
   IF encode(pinned,'hex') IS DISTINCT FROM j->'prompt'->>'content_hash' THEN
     RAISE EXCEPTION 'invalid run provenance'; END IF;
   SELECT content_hash INTO pinned FROM public.output_schema_versions WHERE owner_id = NEW.owner_id
     AND id = (j->'schema_version'->>'id')::bigint;
   IF encode(pinned,'hex') IS DISTINCT FROM j->'schema_version'->>'content_hash' THEN
     RAISE EXCEPTION 'invalid run provenance'; END IF;
   SELECT content_hash INTO pinned FROM public.rubric_version_hashes WHERE owner_id = NEW.owner_id
     AND id = (j->'rubric_binding'->>'id')::bigint;
   IF encode(pinned,'hex') IS DISTINCT FROM j->'rubric_binding'->>'content_hash' THEN
     RAISE EXCEPTION 'invalid run provenance'; END IF;
   IF j->'predecessor' <> 'null'::jsonb THEN
     SELECT content_hash INTO pinned FROM public.model_runs WHERE owner_id = NEW.owner_id
       AND activity_id = (j->>'activity_id')::bigint AND id = (j->'predecessor'->>'id')::bigint;
     IF encode(pinned,'hex') IS DISTINCT FROM j->'predecessor'->>'content_hash' THEN
       RAISE EXCEPTION 'invalid run provenance'; END IF;
   END IF;
   IF encode(public.digest(convert_to(public.tamforge_provenance_canonical(j->'manifest'),
     'UTF8'),'sha256'),'hex') <> j->>'manifest_hash' THEN
     RAISE EXCEPTION 'invalid manifest provenance'; END IF;
   FOR x IN SELECT value FROM jsonb_array_elements(j->'manifest') LOOP
     IF NOT public.tamforge_provenance_hash(x) THEN
       RAISE EXCEPTION 'invalid manifest provenance'; END IF;
   END LOOP;
 ELSE
   SELECT * INTO run FROM public.model_runs WHERE owner_id = NEW.owner_id
     AND id = NEW.run_id FOR UPDATE;
   IF NOT FOUND THEN RAISE EXCEPTION 'invalid run provenance'; END IF;
   IF TG_TABLE_NAME = 'model_run_context_items' THEN
     IF NOT public.tamforge_provenance_context(NEW.owner_id, run.activity_id, j)
       OR j->'reference'->>'attempt_id' <> run.attempt_id::text
       OR run.canonical_json::jsonb->'manifest'->>(j->>'ordinal')::integer <>
         encode(NEW.content_hash,'hex') THEN RAISE EXCEPTION 'invalid context provenance'; END IF;
   ELSE
     IF j->>'run_hash' IS DISTINCT FROM encode(run.content_hash,'hex')
       OR NOT public.tamforge_provenance_int(j->'sequence',1,2147483647) THEN
       RAISE EXCEPTION 'invalid run provenance'; END IF;
     SELECT canonical_json::jsonb INTO previous FROM public.model_run_events
       WHERE run_id = run.id ORDER BY sequence DESC LIMIT 1;
     state := coalesce(previous->'event'->>'state','registered');
     IF TG_TABLE_NAME = 'model_run_events' THEN
       seq := coalesce((previous->>'sequence')::integer,0);
       e := j->'event';
       IF EXISTS(SELECT 1 FROM jsonb_each(e) WHERE value = 'null'::jsonb AND
         key NOT IN ('resolved_model','sdk_version','cli_version','output_hash','error_category'))
       THEN RAISE EXCEPTION 'invalid lifecycle provenance'; END IF;
       IF NOT public.tamforge_provenance_keys(j, ARRAY['format','kind','owner_id','run_hash',
         'sequence','expected_state','event']) OR j->>'kind' <> 'event'
         OR j->>'expected_state' <> state OR (j->>'sequence')::integer <> seq+1
         OR NOT public.tamforge_provenance_keys(e, ARRAY['state','elapsed_ms','resolved_model',
           'sdk_version','cli_version','output_hash','error_category','retry_disposition'])
         OR NOT public.tamforge_provenance_int(e->'elapsed_ms',0,2147483647)
         OR NOT ((state = 'registered' AND e->>'state' IN ('running','failed','cancelled'))
           OR (state = 'running' AND e->>'state' IN ('succeeded','failed','cancelled')))
         OR (previous IS NOT NULL AND (e->>'elapsed_ms')::integer <
            (previous->'event'->>'elapsed_ms')::integer)
         OR e->>'retry_disposition' NOT IN ('none','retryable','exhausted')
         OR (e->>'state' <> 'failed' AND e->>'retry_disposition' <> 'none') THEN
         RAISE EXCEPTION 'invalid lifecycle provenance'; END IF;
       IF e->>'state' = 'running' THEN
         IF NOT public.tamforge_provenance_key(e->'resolved_model')
           OR (e->'sdk_version' = 'null'::jsonb AND e->'cli_version' = 'null'::jsonb)
           OR (e->'sdk_version' <> 'null'::jsonb AND NOT
               public.tamforge_provenance_key(e->'sdk_version'))
           OR (e->'cli_version' <> 'null'::jsonb AND NOT
               public.tamforge_provenance_key(e->'cli_version')) THEN
           RAISE EXCEPTION 'invalid model resolution'; END IF;
       ELSIF e->'resolved_model' <> 'null'::jsonb OR e->'sdk_version' <> 'null'::jsonb
         OR e->'cli_version' <> 'null'::jsonb THEN RAISE EXCEPTION 'invalid model resolution';
       END IF;
       IF (e->>'state' IN ('failed','cancelled')) <> (e->'error_category' <> 'null'::jsonb)
         OR (e->'error_category' <> 'null'::jsonb AND e->>'error_category' NOT IN
           ('invalid_input','permission_required','transient_dependency','resource_exhausted',
            'processing_failure','internal_error','cancelled'))
         OR (e->'output_hash' <> 'null'::jsonb AND (e->>'state' <> 'succeeded' OR
           NOT public.tamforge_provenance_hash(e->'output_hash'))) THEN
         RAISE EXCEPTION 'invalid lifecycle provenance'; END IF;
       IF e->>'state' = 'succeeded' AND EXISTS(SELECT 1 FROM public.agent_tool_calls req
         WHERE req.run_id = run.id AND req.phase_slot = 0 AND NOT EXISTS(
           SELECT 1 FROM public.agent_tool_calls res WHERE res.run_id = run.id
           AND res.call_key = req.call_key AND res.phase_slot = 1)) THEN
         RAISE EXCEPTION 'pending tool calls'; END IF;
     ELSE
       t := j->'audit';
       IF EXISTS(SELECT 1 FROM jsonb_each(t) WHERE value = 'null'::jsonb AND
         key NOT IN ('item_count','error_category')) THEN
         RAISE EXCEPTION 'invalid tool provenance'; END IF;
       SELECT coalesce(max(sequence),0) INTO seq FROM public.agent_tool_calls WHERE run_id = run.id;
       IF NOT public.tamforge_provenance_keys(j, ARRAY['format','kind','owner_id','run_hash',
         'sequence','audit']) OR j->>'kind' <> 'tool' OR state <> 'running'
         OR (j->>'sequence')::integer <> seq+1
         OR NOT public.tamforge_provenance_keys(t, ARRAY['call_key','phase','tool_name',
           'tool_version','schema_hash','elapsed_ms','context_ordinals','item_count','error_category'])
         OR NOT public.tamforge_provenance_key(t->'call_key')
         OR NOT public.tamforge_provenance_key(t->'tool_name')
         OR NOT public.tamforge_provenance_key(t->'tool_version')
         OR NOT public.tamforge_provenance_hash(t->'schema_hash')
         OR NOT public.tamforge_provenance_int(t->'elapsed_ms',0,2147483647)
         OR (t->'item_count' <> 'null'::jsonb AND NOT
           public.tamforge_provenance_int(t->'item_count',0,2147483647))
         OR t->>'phase' NOT IN ('request','succeeded','failed','cancelled')
         OR jsonb_typeof(t->'context_ordinals') <> 'array'
         OR jsonb_array_length(t->'context_ordinals') > 64
         OR (t->>'phase' IN ('failed','cancelled')) <> (t->'error_category' <> 'null'::jsonb)
         OR (t->'error_category' <> 'null'::jsonb AND t->>'error_category' NOT IN
           ('invalid_input','permission_required','transient_dependency','resource_exhausted',
            'processing_failure','internal_error','cancelled')) THEN
         RAISE EXCEPTION 'invalid tool provenance'; END IF;
       IF NOT EXISTS(SELECT 1 FROM public.output_schema_versions WHERE owner_id = NEW.owner_id
         AND encode(content_hash,'hex') = t->>'schema_hash') THEN
         RAISE EXCEPTION 'unknown tool schema'; END IF;
       SELECT count(DISTINCT value) INTO n FROM jsonb_array_elements(t->'context_ordinals');
       IF n <> jsonb_array_length(t->'context_ordinals') THEN
         RAISE EXCEPTION 'invalid tool evidence'; END IF;
       FOR x IN SELECT value FROM jsonb_array_elements(t->'context_ordinals') LOOP
         IF NOT public.tamforge_provenance_int(x,0,63) OR NOT EXISTS(
           SELECT 1 FROM public.model_run_context_items WHERE run_id = run.id
           AND ordinal = (x::text)::integer) THEN RAISE EXCEPTION 'invalid tool evidence'; END IF;
       END LOOP;
       SELECT canonical_json::jsonb->'audit' INTO request FROM public.agent_tool_calls
         WHERE run_id = run.id AND call_key = t->>'call_key' AND phase_slot = 0;
       IF t->>'phase' = 'request' THEN
         IF request IS NOT NULL THEN RAISE EXCEPTION 'duplicate tool request'; END IF;
       ELSE
         IF request IS NULL OR (t->>'elapsed_ms')::integer < (request->>'elapsed_ms')::integer THEN
           RAISE EXCEPTION 'missing tool request'; END IF;
         FOREACH field IN ARRAY ARRAY['tool_name','tool_version','schema_hash',
           'context_ordinals'] LOOP
           IF t->field IS DISTINCT FROM request->field THEN
             RAISE EXCEPTION 'tool request mismatch'; END IF;
         END LOOP;
       END IF;
     END IF;
   END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE FUNCTION public.tamforge_provenance_seal() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE run record; manifest jsonb; n integer; refs integer;
BEGIN
 IF TG_TABLE_NAME = 'model_runs' THEN
   SELECT * INTO run FROM public.model_runs WHERE id = NEW.id;
 ELSE
   SELECT * INTO run FROM public.model_runs WHERE id = NEW.run_id;
 END IF;
 SELECT coalesce(jsonb_agg(encode(content_hash,'hex') ORDER BY ordinal),'[]'::jsonb), count(*),
   count(DISTINCT canonical_json::jsonb->'reference') INTO manifest, n, refs
   FROM public.model_run_context_items WHERE run_id = run.id;
 IF manifest IS DISTINCT FROM run.canonical_json::jsonb->'manifest' OR n <> refs THEN
   RAISE EXCEPTION 'context manifest is not complete'; END IF;
 RETURN NULL;
END $$;
"""

TABLE_NAMES = (
    "prompt_versions",
    "output_schema_versions",
    "rubric_version_hashes",
    "model_runs",
    "model_run_context_items",
    "model_run_events",
    "agent_tool_calls",
)


def upgrade() -> None:
    op.execute(FUNCTIONS)
    op.execute(TABLES)
    op.execute(GUARDS)
    for table in TABLE_NAMES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE OR TRUNCATE "
            f"ON public.{table} FOR EACH STATEMENT "
            "EXECUTE FUNCTION public.tamforge_provenance_immutable()"
        )
        if table not in ("prompt_versions", "output_schema_versions"):
            op.execute(
                f"CREATE TRIGGER trg_{table}_insert BEFORE INSERT ON public.{table} "
                "FOR EACH ROW EXECUTE FUNCTION public.tamforge_provenance_insert()"
            )
    for table in ("model_runs", "model_run_context_items"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER trg_{table}_seal AFTER INSERT ON public.{table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
            "EXECUTE FUNCTION public.tamforge_provenance_seal()"
        )


def downgrade() -> None:
    for table in reversed(TABLE_NAMES):
        op.drop_table(table)
    for function in (
        "seal()",
        "insert()",
        "immutable()",
        "context(bigint,bigint,jsonb)",
        "rubric(bigint,bigint)",
        "pin(jsonb)",
        "hash(jsonb)",
        "key(jsonb)",
        "int(jsonb,bigint,bigint)",
        "keys(jsonb,text[])",
        "canonical(jsonb)",
    ):
        op.execute(f"DROP FUNCTION public.tamforge_provenance_{function}")
