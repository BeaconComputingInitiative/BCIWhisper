// BEACON COMPUTING INITIATIVE
// BCIWhisper Script 58.2 | Engineering Build 2026.10.22-r6.35.2
// Developer Seal: CJB-DEV-2026

#include <pybind11/numpy.h>
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "bciwhisper/audio_metrics.hpp"
#include "bciwhisper/ring_buffer.hpp"

namespace py = pybind11;
using bciwhisper::AudioMetrics;
using bciwhisper::AudioRingBuffer;

PYBIND11_MODULE(_bci_native, m) {
    m.doc() = "BCIWhisper C++20 native audio/DSP primitives";
    m.attr("__bci_script__") = "58.2";
    m.attr("__bci_abi__") = 1;

    py::class_<AudioMetrics>(m, "AudioMetrics")
        .def_readonly("rms", &AudioMetrics::rms)
        .def_readonly("peak", &AudioMetrics::peak)
        .def_readonly("zero_crossing_rate", &AudioMetrics::zero_crossing_rate)
        .def_readonly("dc_offset", &AudioMetrics::dc_offset);

    m.def(
        "analyze_audio",
        [](py::array_t<float, py::array::c_style | py::array::forcecast> input) {
            py::buffer_info info = input.request();
            const auto *ptr = static_cast<const float *>(info.ptr);
            const auto count = static_cast<std::size_t>(info.size);

            py::gil_scoped_release release;
            return bciwhisper::analyze_audio(
                std::span<const float>(ptr, count)
            );
        },
        py::arg("samples")
    );

    py::class_<AudioRingBuffer>(m, "AudioRingBuffer")
        .def(py::init<std::size_t>(), py::arg("capacity"))
        .def_property_readonly("capacity", &AudioRingBuffer::capacity)
        .def_property_readonly("size", &AudioRingBuffer::size)
        .def_property_readonly("overwritten", &AudioRingBuffer::overwritten)
        .def("clear", &AudioRingBuffer::clear)
        .def(
            "write",
            [](AudioRingBuffer &self,
               py::array_t<float, py::array::c_style | py::array::forcecast> input) {
                py::buffer_info info = input.request();
                const auto *ptr = static_cast<const float *>(info.ptr);
                const auto count = static_cast<std::size_t>(info.size);
                py::gil_scoped_release release;
                self.write(std::span<const float>(ptr, count));
            }
        )
        .def("read", &AudioRingBuffer::read, py::arg("count"))
        .def(
            "snapshot_latest",
            &AudioRingBuffer::snapshot_latest,
            py::arg("count")
        );
}
