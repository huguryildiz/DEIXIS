//! The backend on Windows (P10 W4): created inside a fresh Job Object, never outside one.
//!
//! The shell has no job above it, so `spawn` makes a job with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (no breakaway
//! flags) and creates the process inside it at creation, through `PROC_THREAD_ATTRIBUTE_JOB_LIST`. Only the three pipe
//! ends the child needs are inherited (`PROC_THREAD_ATTRIBUTE_HANDLE_LIST`); the shell's pipe ends and the job handle
//! are not inheritable. If any step fails, no process exists and the error comes back as text. When the shell dies,
//! its last job handle closes and the job takes the backend and every descendant with it.

use std::ffi::{OsStr, OsString};
use std::fs::File;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::io::FromRawHandle;
use std::path::Path;
use std::sync::Arc;
use std::time::{Duration, Instant};

use windows_sys::Win32::Foundation::{
    CloseHandle, SetHandleInformation, HANDLE, HANDLE_FLAG_INHERIT, INVALID_HANDLE_VALUE, WAIT_OBJECT_0,
};
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::System::JobObjects::{
    CreateJobObjectW, JobObjectBasicAccountingInformation, JobObjectExtendedLimitInformation, QueryInformationJobObject,
    SetInformationJobObject, TerminateJobObject, JOBOBJECT_BASIC_ACCOUNTING_INFORMATION,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
};
use windows_sys::Win32::System::Pipes::CreatePipe;
use windows_sys::Win32::System::Threading::{
    CreateProcessW, DeleteProcThreadAttributeList, InitializeProcThreadAttributeList, UpdateProcThreadAttribute,
    WaitForSingleObject, CREATE_NO_WINDOW, CREATE_UNICODE_ENVIRONMENT, EXTENDED_STARTUPINFO_PRESENT, INFINITE,
    LPPROC_THREAD_ATTRIBUTE_LIST, PROCESS_INFORMATION, PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
    PROC_THREAD_ATTRIBUTE_JOB_LIST, STARTF_USESTDHANDLES, STARTUPINFOEXW,
};

/// A handle closed once, when its last owner drops it.
struct Owned(HANDLE);

// A kernel handle may be used from any thread; Owned only closes it in Drop.
unsafe impl Send for Owned {}
unsafe impl Sync for Owned {}

impl Drop for Owned {
    fn drop(&mut self) {
        if !self.0.is_null() && self.0 != INVALID_HANDLE_VALUE {
            unsafe { CloseHandle(self.0) };
        }
    }
}

/// The backend's process and its job. Dropping it closes both handles, which (KILL_ON_JOB_CLOSE) ends what is left.
pub struct Backend {
    job: Owned,
    process: Arc<Owned>,
}

/// Waits for the process to end; holds its own reference to the process handle, so the handle stays open until the
/// wait returns even when the Backend is dropped meanwhile.
pub struct Waiter(Arc<Owned>);

impl Waiter {
    pub fn wait(self) {
        unsafe { WaitForSingleObject(self.0 .0, INFINITE) };
    }
}

impl Backend {
    pub fn exited(&self) -> bool {
        unsafe { WaitForSingleObject(self.process.0, 0) == WAIT_OBJECT_0 }
    }

    pub fn waiter(&self) -> Waiter {
        Waiter(self.process.clone())
    }

    /// End every process in the job (the backend and all its descendants) and wait, at most `wait`, until the job is
    /// empty: termination is asynchronous, and a restart must not race processes that still hold the library's locks.
    /// True when no process is left.
    pub fn terminate_job(&self, wait: Duration) -> bool {
        unsafe { TerminateJobObject(self.job.0, 1) };
        let ends = Instant::now() + wait;
        loop {
            let mut info: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = unsafe { std::mem::zeroed() };
            let ok = unsafe {
                QueryInformationJobObject(
                    self.job.0,
                    JobObjectBasicAccountingInformation,
                    &mut info as *mut _ as *mut core::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
                    std::ptr::null_mut(),
                )
            };
            if ok != 0 && info.ActiveProcesses == 0 {
                return true;
            }
            if Instant::now() >= ends {
                return false;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }
}

pub struct Spawned {
    pub backend: Backend,
    pub stdin: File,
    pub stdout: File,
    pub stderr: File,
}

pub fn wide(text: &OsStr) -> Vec<u16> {
    text.encode_wide().chain(std::iter::once(0)).collect()
}

fn last_error(step: &str) -> String {
    format!("{step}: {}", std::io::Error::last_os_error())
}

/// One argument quoted for CommandLineToArgvW (the rules the C runtime and Python use to split a command line).
pub fn quote(arg: &str) -> String {
    if !arg.is_empty() && !arg.contains([' ', '\t', '\n', '\u{b}', '"']) {
        return arg.to_string();
    }
    let mut out = String::from("\"");
    let mut backslashes = 0;
    for c in arg.chars() {
        match c {
            '\\' => backslashes += 1,
            '"' => {
                out.push_str(&"\\".repeat(backslashes * 2 + 1));
                out.push('"');
                backslashes = 0;
            }
            _ => {
                out.push_str(&"\\".repeat(backslashes));
                out.push(c);
                backslashes = 0;
            }
        }
    }
    out.push_str(&"\\".repeat(backslashes * 2));
    out.push('"');
    out
}

/// A Unicode environment block: `name=value\0 ... \0`, sorted by name without regard to case, as Windows expects.
fn environment_block(mut vars: Vec<(OsString, OsString)>) -> Vec<u16> {
    vars.sort_by_key(|(name, _)| name.to_string_lossy().to_uppercase());
    let mut block = Vec::new();
    for (name, value) in vars {
        block.extend(name.encode_wide());
        block.push(u16::from(b'='));
        block.extend(value.encode_wide());
        block.push(0);
    }
    if block.is_empty() {
        block.push(0);
    }
    block.push(0);
    block
}

/// A pipe whose `child` end is inheritable and whose `parent` end is not.
fn pipe(child_reads: bool) -> Result<(Owned, Owned), String> {
    let attributes = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: std::ptr::null_mut(),
        bInheritHandle: 1,
    };
    let (mut read, mut write): (HANDLE, HANDLE) = (std::ptr::null_mut(), std::ptr::null_mut());
    if unsafe { CreatePipe(&mut read, &mut write, &attributes, 0) } == 0 {
        return Err(last_error("CreatePipe"));
    }
    let (read, write) = (Owned(read), Owned(write));
    let (child, parent) = if child_reads { (read, write) } else { (write, read) };
    if unsafe { SetHandleInformation(parent.0, HANDLE_FLAG_INHERIT, 0) } == 0 {
        return Err(last_error("SetHandleInformation"));
    }
    Ok((child, parent))
}

/// A job that ends every process in it when its last handle closes, with no breakaway allowed.
fn kill_on_close_job() -> Result<Owned, String> {
    // No security attributes: the handle is not inheritable.
    let job = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
    if job.is_null() {
        return Err(last_error("CreateJobObjectW"));
    }
    let job = Owned(job);
    let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { std::mem::zeroed() };
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    let set = unsafe {
        SetInformationJobObject(
            job.0,
            JobObjectExtendedLimitInformation,
            &limits as *const _ as *const core::ffi::c_void,
            std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        )
    };
    if set == 0 {
        return Err(last_error("SetInformationJobObject"));
    }
    Ok(job)
}

/// A process-thread attribute list with room for `count` attributes; deleted when dropped.
struct Attributes(Vec<usize>);

impl Attributes {
    fn new(count: u32) -> Result<Self, String> {
        let mut size = 0usize;
        unsafe { InitializeProcThreadAttributeList(std::ptr::null_mut(), count, 0, &mut size) };
        if size == 0 {
            return Err(last_error("InitializeProcThreadAttributeList (size)"));
        }
        let mut list = Attributes(vec![0usize; size.div_ceil(std::mem::size_of::<usize>())]);
        if unsafe { InitializeProcThreadAttributeList(list.ptr(), count, 0, &mut size) } == 0 {
            list.0.clear(); // never initialised: nothing to delete
            return Err(last_error("InitializeProcThreadAttributeList"));
        }
        Ok(list)
    }

    fn ptr(&mut self) -> LPPROC_THREAD_ATTRIBUTE_LIST {
        self.0.as_mut_ptr() as LPPROC_THREAD_ATTRIBUTE_LIST
    }

    /// `values` must outlive the CreateProcessW call that uses this list.
    fn set(&mut self, attribute: u32, values: &[HANDLE], name: &str) -> Result<(), String> {
        let done = unsafe {
            UpdateProcThreadAttribute(
                self.ptr(),
                0,
                attribute as usize,
                values.as_ptr() as *const core::ffi::c_void,
                std::mem::size_of_val(values),
                std::ptr::null_mut(),
                std::ptr::null(),
            )
        };
        if done == 0 {
            return Err(last_error(name));
        }
        Ok(())
    }
}

impl Drop for Attributes {
    fn drop(&mut self) {
        if !self.0.is_empty() {
            unsafe { DeleteProcThreadAttributeList(self.ptr()) };
        }
    }
}

/// Create `exe args...` inside a fresh kill-on-close job, with piped stdin, stdout and stderr and no console window.
/// `env` is the child's whole environment; `cwd` its working folder.
pub fn spawn(exe: &Path, args: &[&str], env: Vec<(OsString, OsString)>, cwd: Option<&Path>) -> Result<Spawned, String> {
    let job = kill_on_close_job()?;
    let (stdin_child, stdin_parent) = pipe(true)?;
    let (stdout_child, stdout_parent) = pipe(false)?;
    let (stderr_child, stderr_parent) = pipe(false)?;

    let inherited = [stdin_child.0, stdout_child.0, stderr_child.0];
    let jobs = [job.0];
    let mut attributes = Attributes::new(2)?;
    attributes.set(PROC_THREAD_ATTRIBUTE_HANDLE_LIST, &inherited, "UpdateProcThreadAttribute (handle list)")?;
    attributes.set(PROC_THREAD_ATTRIBUTE_JOB_LIST, &jobs, "UpdateProcThreadAttribute (job list)")?;

    let mut startup: STARTUPINFOEXW = unsafe { std::mem::zeroed() };
    startup.StartupInfo.cb = std::mem::size_of::<STARTUPINFOEXW>() as u32;
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = stdin_child.0;
    startup.StartupInfo.hStdOutput = stdout_child.0;
    startup.StartupInfo.hStdError = stderr_child.0;
    startup.lpAttributeList = attributes.ptr();

    let application = wide(exe.as_os_str());
    let line: Vec<String> = std::iter::once(exe.to_string_lossy().into_owned())
        .chain(args.iter().map(|a| a.to_string()))
        .map(|a| quote(&a))
        .collect();
    let mut command_line = wide(OsStr::new(&line.join(" ")));
    let environment = environment_block(env);
    let directory = cwd.map(|d| wide(d.as_os_str()));
    let mut info: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    let created = unsafe {
        CreateProcessW(
            application.as_ptr(),
            command_line.as_mut_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            1, // inherit only the handles in the list above
            EXTENDED_STARTUPINFO_PRESENT | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
            environment.as_ptr() as *const core::ffi::c_void,
            directory.as_ref().map_or(std::ptr::null(), |d| d.as_ptr()),
            &startup.StartupInfo,
            &mut info,
        )
    };
    if created == 0 {
        return Err(last_error("CreateProcessW"));
    }
    drop(attributes);
    drop(Owned(info.hThread));
    // The child's ends now live in the child; the shell keeps only its own.
    drop((stdin_child, stdout_child, stderr_child));
    let file = |handle: Owned| {
        let raw = handle.0;
        std::mem::forget(handle);
        unsafe { File::from_raw_handle(raw as _) }
    };
    Ok(Spawned {
        backend: Backend { job, process: Arc::new(Owned(info.hProcess)) },
        stdin: file(stdin_parent),
        stdout: file(stdout_parent),
        stderr: file(stderr_parent),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;
    use std::time::{Duration, Instant};

    fn cmd() -> std::path::PathBuf {
        let root = std::env::var_os("SystemRoot").unwrap_or_else(|| "C:\\Windows".into());
        Path::new(&root).join("System32").join("cmd.exe")
    }

    #[test]
    fn quotes_like_the_c_runtime_splits() {
        assert_eq!(quote("serve"), "serve");
        assert_eq!(quote("C:\\Program Files\\DEIXIS\\a.exe"), "\"C:\\Program Files\\DEIXIS\\a.exe\"");
        assert_eq!(quote("a\"b"), "\"a\\\"b\"");
        assert_eq!(quote("end\\ "), "\"end\\ \"");
        assert_eq!(quote("trail\\"), "trail\\");
        assert_eq!(quote(""), "\"\"");
    }

    #[test]
    fn child_runs_inside_the_job_with_pipes() {
        let env: Vec<_> = std::env::vars_os().collect();
        let mut spawned = spawn(&cmd(), &["/c", "echo", "deixis"], env, None).expect("spawn");
        let mut out = String::new();
        spawned.stdout.read_to_string(&mut out).unwrap();
        assert_eq!(out.trim(), "deixis");
        spawned.backend.waiter().wait();
        assert!(spawned.backend.exited());
    }

    #[test]
    fn terminating_the_job_ends_the_child_and_its_child() {
        let env: Vec<_> = std::env::vars_os().collect();
        // cmd starts ping as its own child; both are in the job.
        let spawned = spawn(&cmd(), &["/c", "ping", "-n", "60", "127.0.0.1"], env, None).expect("spawn");
        assert!(!spawned.backend.exited());
        let started = Instant::now();
        assert!(spawned.backend.terminate_job(Duration::from_secs(5)), "the job still has processes");
        spawned.backend.waiter().wait();
        assert!(spawned.backend.exited());
        assert!(started.elapsed() < Duration::from_secs(5));
        // stdout reaches EOF only when every holder of the pipe's write end (cmd and ping) has ended.
        let mut stdout = spawned.stdout;
        let mut rest = Vec::new();
        stdout.read_to_end(&mut rest).unwrap();
    }

    #[test]
    fn a_missing_program_leaves_no_process() {
        let err = spawn(Path::new("C:\\no\\such\\deixis-backend.exe"), &["serve"], vec![], None).err().expect("refused");
        assert!(err.starts_with("CreateProcessW"), "{err}");
    }
}
