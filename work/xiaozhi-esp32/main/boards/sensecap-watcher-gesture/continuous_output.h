#pragma once

// Default permission survives STOP and temporary readiness failures. Actual
// output still needs a neutral receipt, fresh input and a new ARM epoch.
class ContinuousOutput {
    bool enabled_ = true;
public:
    bool Enabled() const { return enabled_; }
    void SetEnabled(bool enabled) { enabled_ = enabled; }
    bool ShouldArm(bool ready, bool wanted, bool applied, bool in_flight) const {
        return enabled_ && ready && !wanted && !applied && !in_flight;
    }
};
