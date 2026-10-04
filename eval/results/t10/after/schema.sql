--
-- PostgreSQL database dump
--

\restrict Ibe9yfcqh9sx7L0AjIC8IDLWbNHRB8KjLbOQvAZxmmrB3he2maXNsWC6cluDmjc

-- Dumped from database version 16.15
-- Dumped by pg_dump version 16.15

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: vector; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;


--
-- Name: EXTENSION vector; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION vector IS 'vector data type and ivfflat and hnsw access methods';


--
-- Name: sessionstatus; Type: TYPE; Schema: public; Owner: -
--

CREATE TYPE public.sessionstatus AS ENUM (
    'pending',
    'transcribing',
    'diarising',
    'awaiting_role_confirmation',
    'scoring',
    'generating',
    'completed',
    'failed'
);


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evaluations (
    id uuid NOT NULL,
    session_id uuid NOT NULL,
    interpreter_speaker character varying(32),
    client_speaker character varying(32),
    transcript jsonb,
    semantic_similarity_scores jsonb,
    llm_feedback text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    structured_issues jsonb,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    client_translations jsonb,
    aligned_blocks jsonb,
    role_warnings jsonb,
    short_turns_skipped integer DEFAULT 0 NOT NULL,
    language_confidence character varying(10) DEFAULT 'high'::character varying NOT NULL,
    language_validation_passed boolean DEFAULT true NOT NULL,
    timestamp_mapping_issues integer,
    asr_confidence_distribution jsonb
);


--
-- Name: knowledge_chunks; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.knowledge_chunks (
    id uuid NOT NULL,
    source_id character varying(128) NOT NULL,
    category character varying(32) NOT NULL,
    title character varying(512) NOT NULL,
    content text NOT NULL,
    metadata jsonb,
    embedding public.vector(768) NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessions (
    id uuid NOT NULL,
    filename character varying(255) NOT NULL,
    audio_path character varying(512) NOT NULL,
    language character varying(10) DEFAULT 'nl'::character varying NOT NULL,
    ind_case_id character varying(100),
    status public.sessionstatus DEFAULT 'pending'::public.sessionstatus NOT NULL,
    duration_seconds double precision,
    error_code character varying(64),
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    owner_id uuid NOT NULL,
    known_terms text,
    audio_deleted_at timestamp with time zone
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id uuid NOT NULL,
    email character varying(255) NOT NULL,
    hashed_password character varying(255) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    failed_login_count integer DEFAULT 0 NOT NULL,
    locked_until timestamp with time zone,
    token_version integer DEFAULT 0 NOT NULL
);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: evaluations evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluations
    ADD CONSTRAINT evaluations_pkey PRIMARY KEY (id);


--
-- Name: knowledge_chunks knowledge_chunks_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.knowledge_chunks
    ADD CONSTRAINT knowledge_chunks_pkey PRIMARY KEY (id);


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_evaluations_session_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_evaluations_session_id ON public.evaluations USING btree (session_id);


--
-- Name: ix_knowledge_chunks_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_chunks_category ON public.knowledge_chunks USING btree (category);


--
-- Name: ix_knowledge_chunks_embedding_hnsw; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_chunks_embedding_hnsw ON public.knowledge_chunks USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: ix_knowledge_chunks_source_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_knowledge_chunks_source_id ON public.knowledge_chunks USING btree (source_id);


--
-- Name: ix_sessions_owner_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ix_sessions_owner_id ON public.sessions USING btree (owner_id);


--
-- Name: ix_users_email; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);


--
-- Name: evaluations evaluations_session_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluations
    ADD CONSTRAINT evaluations_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.sessions(id) ON DELETE CASCADE;


--
-- Name: sessions sessions_owner_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.users(id);


--
-- PostgreSQL database dump complete
--

\unrestrict Ibe9yfcqh9sx7L0AjIC8IDLWbNHRB8KjLbOQvAZxmmrB3he2maXNsWC6cluDmjc

