// P10 W3 DLL probe, the outside program: `probe-<name>.exe` loads `<name>.dll` by name through the standard search
// order, as any external tool would, and says which copy it got. Exit 0: the outside copy (it has the marker export);
// 3: a copy without the marker (the packaged backend's); 4: nothing loaded.
use std::ffi::c_void;

#[link(name = "kernel32")]
extern "system" {
    fn LoadLibraryW(name: *const u16) -> *mut c_void;
    fn GetProcAddress(module: *mut c_void, name: *const u8) -> *mut c_void;
    fn GetModuleFileNameW(module: *mut c_void, buffer: *mut u16, size: u32) -> u32;
}

fn main() {
    let exe = std::env::current_exe().expect("own path");
    let stem = exe.file_stem().expect("file name").to_string_lossy().to_string();
    let dll = format!("{}.dll", stem.trim_start_matches("probe-"));
    let wide: Vec<u16> = dll.encode_utf16().chain(Some(0)).collect();
    let module = unsafe { LoadLibraryW(wide.as_ptr()) };
    if module.is_null() {
        println!("not loaded: {dll}");
        std::process::exit(4);
    }
    let mut buffer = [0u16; 2048];
    let length = unsafe { GetModuleFileNameW(module, buffer.as_mut_ptr(), buffer.len() as u32) } as usize;
    let path = String::from_utf16_lossy(&buffer[..length]);
    if unsafe { GetProcAddress(module, b"deixis_probe_marker\0".as_ptr()) }.is_null() {
        println!("loaded a copy without the marker: {path}");
        std::process::exit(3);
    }
    println!("loaded the outside copy: {path}");
}
