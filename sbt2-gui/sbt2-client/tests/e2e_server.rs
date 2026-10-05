//! Runs the client against the real `sbt2-server`, started with uv from `sbt2-backend`.
//! `SBT2_E2E_UV` names the uv command and `SBT2_E2E_PORT` the port; the defaults are `uv`
//! and a free port.

use std::{
    env, fs,
    net::TcpListener,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    time::{Duration, Instant},
};

use sbt2_client::{
    Client, ClientError, ServerAddress, Session, Token,
    protocol::{Capability, RunFilter},
};
use tempfile::TempDir;

const TOKEN: &str = "e2e-token";
const STARTUP: Duration = Duration::from_secs(180);

struct RealServer {
    process: Child,
    address: ServerAddress,
    folder: TempDir,
}

impl RealServer {
    fn start() -> Self {
        let folder = TempDir::new().unwrap();
        let port = env::var("SBT2_E2E_PORT").unwrap_or_else(|_| free_port().to_string());
        let process = spawn(folder.path(), &port);
        let address = ServerAddress::parse(&format!("ws://127.0.0.1:{port}")).unwrap();
        Self {
            process,
            address,
            folder,
        }
    }

    async fn connect(&self) -> Session {
        let deadline = Instant::now() + STARTUP;
        loop {
            let client = Client::new(self.address.clone(), Token::new(TOKEN));
            match client.connect().await {
                Ok(session) => return session,
                Err(ClientError::Unauthorized) => panic!("the server refused the token"),
                Err(error) if Instant::now() > deadline => panic!("no server: {error}"),
                Err(_) => tokio::time::sleep(Duration::from_millis(500)).await,
            }
        }
    }

    fn stored_run_id(&self) -> String {
        fs::read_to_string(self.folder.path().join("run-id")).unwrap()
    }
}

impl Drop for RealServer {
    fn drop(&mut self) {
        drop(self.process.stdin.take());
        let _ = self.process.wait();
    }
}

fn free_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.local_addr().unwrap().port()
}

fn backend() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../sbt2-backend")
}

fn spawn(folder: &Path, port: &str) -> Child {
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/support/serve_one_run.py");
    let uv = env::var("SBT2_E2E_UV").unwrap_or_else(|_| "uv".to_owned());
    Command::new(uv)
        .arg("--directory")
        .arg(backend())
        .args(["run", "--locked", "python"])
        .arg(script)
        .arg(folder.join("data"))
        .arg(folder.join("config"))
        .arg(port)
        .arg(folder.join("run-id"))
        .env("SBT2_SERVER_TOKEN", TOKEN)
        .stdin(Stdio::piped())
        .spawn()
        .expect("uv starts")
}

#[tokio::test]
#[ignore = "starts the real server"]
async fn e2e_lists_the_stored_run_of_a_real_server() {
    let server = RealServer::start();

    let session = server.connect().await;

    assert!(
        session
            .welcome()
            .capabilities
            .contains(&(Capability::Results as i32))
    );
    let runs = session.list_runs(RunFilter::default()).await.unwrap();
    let ids: Vec<_> = runs.iter().map(|run| run.run_id.as_str()).collect();
    assert_eq!(ids, [server.stored_run_id()]);
}
