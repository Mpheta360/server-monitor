-- Create profiles table (stores user profile data)
CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL UNIQUE,
    username VARCHAR(128),
    full_name VARCHAR(255),
    avatar_url TEXT,
    role VARCHAR(32) DEFAULT 'viewer',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_profiles_email ON profiles(email);

-- Create servers table
CREATE TABLE IF NOT EXISTS servers (
    id SERIAL PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    hostname VARCHAR(255) NOT NULL,
    ip_address VARCHAR(64) DEFAULT '',
    environment VARCHAR(64) DEFAULT 'production',
    tags TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_servers_user_hostname ON servers(user_id, hostname);
CREATE INDEX IF NOT EXISTS idx_servers_user_id ON servers(user_id);

-- Create metrics table
CREATE TABLE IF NOT EXISTS metrics (
    id SERIAL PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    cpu_percent FLOAT NOT NULL,
    memory_percent FLOAT NOT NULL,
    disk_percent FLOAT NOT NULL,
    load_1m FLOAT DEFAULT 0.0,
    load_5m FLOAT DEFAULT 0.0,
    load_15m FLOAT DEFAULT 0.0,
    uptime_seconds INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_metrics_server_id ON metrics(server_id);
CREATE INDEX IF NOT EXISTS idx_metrics_user_id ON metrics(user_id);
CREATE INDEX IF NOT EXISTS idx_metrics_created_at ON metrics(created_at);

-- Create service_statuses table
CREATE TABLE IF NOT EXISTS service_statuses (
    id SERIAL PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    status VARCHAR(32) DEFAULT 'unknown',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_service_statuses_server_id ON service_statuses(server_id);
CREATE INDEX IF NOT EXISTS idx_service_statuses_user_id ON service_statuses(user_id);
CREATE INDEX IF NOT EXISTS idx_service_statuses_name ON service_statuses(name);
CREATE INDEX IF NOT EXISTS idx_service_statuses_created_at ON service_statuses(created_at);

-- Create nginx_metrics table
CREATE TABLE IF NOT EXISTS nginx_metrics (
    id SERIAL PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    active_connections INTEGER DEFAULT 0,
    accepts_total INTEGER DEFAULT 0,
    handled_total INTEGER DEFAULT 0,
    requests_total INTEGER DEFAULT 0,
    reading INTEGER DEFAULT 0,
    writing INTEGER DEFAULT 0,
    waiting INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_nginx_metrics_server_id ON nginx_metrics(server_id);
CREATE INDEX IF NOT EXISTS idx_nginx_metrics_user_id ON nginx_metrics(user_id);
CREATE INDEX IF NOT EXISTS idx_nginx_metrics_created_at ON nginx_metrics(created_at);

-- Create alert_events table
CREATE TABLE IF NOT EXISTS alert_events (
    id SERIAL PRIMARY KEY,
    server_id INTEGER REFERENCES servers(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    alert_key VARCHAR(255) NOT NULL,
    severity VARCHAR(32) DEFAULT 'critical',
    message TEXT NOT NULL,
    source VARCHAR(64) DEFAULT 'ingest',
    delivered BOOLEAN DEFAULT FALSE,
    suppressed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alert_events_server_id ON alert_events(server_id);
CREATE INDEX IF NOT EXISTS idx_alert_events_user_id ON alert_events(user_id);
CREATE INDEX IF NOT EXISTS idx_alert_events_alert_key ON alert_events(alert_key);
CREATE INDEX IF NOT EXISTS idx_alert_events_created_at ON alert_events(created_at);

-- Enable RLS (Row Level Security)
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE servers ENABLE ROW LEVEL SECURITY;
ALTER TABLE metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE service_statuses ENABLE ROW LEVEL SECURITY;
ALTER TABLE nginx_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_events ENABLE ROW LEVEL SECURITY;

-- RLS Policies for profiles
DROP POLICY IF EXISTS "Users can view own profile" ON profiles;
CREATE POLICY "Users can view own profile" ON profiles FOR SELECT USING (auth.uid() = id);

DROP POLICY IF EXISTS "Users can update own profile" ON profiles;
CREATE POLICY "Users can update own profile" ON profiles FOR UPDATE USING (auth.uid() = id);

-- RLS Policies for servers
DROP POLICY IF EXISTS "Users can view own servers" ON servers;
CREATE POLICY "Users can view own servers" ON servers FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own servers" ON servers;
CREATE POLICY "Users can insert own servers" ON servers FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own servers" ON servers;
CREATE POLICY "Users can update own servers" ON servers FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete own servers" ON servers;
CREATE POLICY "Users can delete own servers" ON servers FOR DELETE USING (auth.uid() = user_id);

-- RLS Policies for metrics
DROP POLICY IF EXISTS "Users can view own metrics" ON metrics;
CREATE POLICY "Users can view own metrics" ON metrics FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own metrics" ON metrics;
CREATE POLICY "Users can insert own metrics" ON metrics FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete own metrics" ON metrics;
CREATE POLICY "Users can delete own metrics" ON metrics FOR DELETE USING (auth.uid() = user_id);

-- RLS Policies for service_statuses
DROP POLICY IF EXISTS "Users can view own service statuses" ON service_statuses;
CREATE POLICY "Users can view own service statuses" ON service_statuses FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own service statuses" ON service_statuses;
CREATE POLICY "Users can insert own service statuses" ON service_statuses FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own service statuses" ON service_statuses;
CREATE POLICY "Users can update own service statuses" ON service_statuses FOR UPDATE USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete own service statuses" ON service_statuses;
CREATE POLICY "Users can delete own service statuses" ON service_statuses FOR DELETE USING (auth.uid() = user_id);

-- RLS Policies for nginx_metrics
DROP POLICY IF EXISTS "Users can view own nginx metrics" ON nginx_metrics;
CREATE POLICY "Users can view own nginx metrics" ON nginx_metrics FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own nginx metrics" ON nginx_metrics;
CREATE POLICY "Users can insert own nginx metrics" ON nginx_metrics FOR INSERT WITH CHECK (auth.uid() = user_id);

-- RLS Policies for alert_events
DROP POLICY IF EXISTS "Users can view own alerts" ON alert_events;
CREATE POLICY "Users can view own alerts" ON alert_events FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own alerts" ON alert_events;
CREATE POLICY "Users can update own alerts" ON alert_events FOR UPDATE USING (auth.uid() = user_id);

-- Create function to handle new user profile creation
DROP FUNCTION IF EXISTS public.handle_new_user() CASCADE;
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS trigger AS $$
BEGIN
    INSERT INTO public.profiles (id, email, username, full_name)
    VALUES (NEW.id, NEW.email, NEW.raw_user_meta_data ->> 'username', NEW.raw_user_meta_data ->> 'full_name');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to create profile on new auth user
DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE PROCEDURE public.handle_new_user();
