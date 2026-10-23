// BEACON COMPUTING INITIATIVE
// BCIWhisper Script 58.2 | Engineering Build 2026.10.22-r6.35.2
// Developer Seal: CJB-DEV-2026

#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <span>

namespace bciwhisper {

struct AudioMetrics {
    double rms = 0.0;
    double peak = 0.0;
    double zero_crossing_rate = 0.0;
    double dc_offset = 0.0;
};

inline AudioMetrics analyze_audio(std::span<const float> samples) noexcept {
    AudioMetrics out{};
    if (samples.empty()) {
        return out;
    }

    long double sum_sq = 0.0L;
    long double sum = 0.0L;
    std::size_t crossings = 0;
    float previous = samples.front();

    for (std::size_t i = 0; i < samples.size(); ++i) {
        const float sample = std::isfinite(samples[i]) ? samples[i] : 0.0F;
        const double d = static_cast<double>(sample);

        sum_sq += static_cast<long double>(d * d);
        sum += static_cast<long double>(d);
        out.peak = std::max(out.peak, std::abs(d));

        if (i > 0) {
            const bool crossed =
                (previous < 0.0F && sample >= 0.0F) ||
                (previous >= 0.0F && sample < 0.0F);
            if (crossed) {
                ++crossings;
            }
        }

        previous = sample;
    }

    const auto n = static_cast<long double>(samples.size());
    out.rms = std::sqrt(static_cast<double>(sum_sq / n));
    out.dc_offset = static_cast<double>(sum / n);
    out.zero_crossing_rate =
        samples.size() > 1
            ? static_cast<double>(crossings) /
                  static_cast<double>(samples.size() - 1)
            : 0.0;

    return out;
}

}  // namespace bciwhisper
