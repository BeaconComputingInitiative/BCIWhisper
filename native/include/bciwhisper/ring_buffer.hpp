// BEACON COMPUTING INITIATIVE
// BCIWhisper Script 58.2 | Engineering Build 2026.10.22-r6.35.2
// Developer Seal: CJB-DEV-2026

#pragma once

#include <algorithm>
#include <cstddef>
#include <mutex>
#include <span>
#include <stdexcept>
#include <vector>

namespace bciwhisper {

class AudioRingBuffer {
public:
    explicit AudioRingBuffer(std::size_t capacity)
        : buffer_(capacity, 0.0F) {
        if (capacity == 0) {
            throw std::invalid_argument("capacity must be > 0");
        }
    }

    std::size_t capacity() const noexcept {
        return buffer_.size();
    }

    std::size_t size() const noexcept {
        std::scoped_lock lock(mutex_);
        return size_;
    }

    std::size_t overwritten() const noexcept {
        std::scoped_lock lock(mutex_);
        return overwritten_;
    }

    void clear() noexcept {
        std::scoped_lock lock(mutex_);
        head_ = 0;
        tail_ = 0;
        size_ = 0;
        overwritten_ = 0;
    }

    void write(std::span<const float> samples) {
        std::scoped_lock lock(mutex_);

        for (const float sample : samples) {
            buffer_[head_] = sample;
            head_ = (head_ + 1) % buffer_.size();

            if (size_ == buffer_.size()) {
                tail_ = (tail_ + 1) % buffer_.size();
                ++overwritten_;
            } else {
                ++size_;
            }
        }
    }

    std::vector<float> read(std::size_t count) {
        std::scoped_lock lock(mutex_);
        const std::size_t take = std::min(count, size_);

        std::vector<float> out;
        out.reserve(take);

        for (std::size_t i = 0; i < take; ++i) {
            out.push_back(buffer_[tail_]);
            tail_ = (tail_ + 1) % buffer_.size();
        }

        size_ -= take;
        return out;
    }

    std::vector<float> snapshot_latest(std::size_t count) const {
        std::scoped_lock lock(mutex_);
        const std::size_t take = std::min(count, size_);

        std::vector<float> out;
        out.reserve(take);

        const std::size_t start =
            (head_ + buffer_.size() - take) % buffer_.size();

        for (std::size_t i = 0; i < take; ++i) {
            out.push_back(buffer_[(start + i) % buffer_.size()]);
        }

        return out;
    }

private:
    mutable std::mutex mutex_;
    std::vector<float> buffer_;
    std::size_t head_ = 0;
    std::size_t tail_ = 0;
    std::size_t size_ = 0;
    std::size_t overwritten_ = 0;
};

}  // namespace bciwhisper
