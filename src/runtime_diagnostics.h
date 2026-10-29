#pragma once

// Opt-in evidence collection. Production builds compile these hooks away.
#if defined(ESP32) && defined(RATGDO_RUNTIME_DIAGNOSTICS)
void runtime_diagnostics_setup();
void runtime_diagnostics_phase(unsigned phase);
void runtime_diagnostics_homekit_progress();
#else
inline void runtime_diagnostics_setup() {}
inline void runtime_diagnostics_phase(unsigned) {}
inline void runtime_diagnostics_homekit_progress() {}
#endif
