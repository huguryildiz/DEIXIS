// P10 W3 DLL probe, the outside copy: built by scripts/desktop/sidecar_smoke.py under the name of a DLL the packaged
// backend's _internal folder holds. Only this copy exports the marker.
#[no_mangle]
pub extern "C" fn deixis_probe_marker() -> u32 {
    0xD1C5
}
