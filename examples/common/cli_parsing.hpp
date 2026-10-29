#pragma once

#include <cstdint>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <utility>

namespace qwen_tts_examples::cli {

template <typename ArgumentGetter>
std::string require_value(
    int& index,
    int argc,
    const std::string& current,
    ArgumentGetter&& argument_at,
    const std::string& option) {
    const std::string prefix = option + '=';
    if (current.rfind(prefix, 0) == 0) {
        return current.substr(prefix.size());
    }
    if (index + 1 >= argc) {
        throw std::runtime_error("missing value for " + option);
    }
    ++index;
    return std::forward<ArgumentGetter>(argument_at)(index);
}

namespace detail {

inline std::runtime_error invalid_integer(
    const std::string& value,
    const std::string& option) {
    return std::runtime_error("invalid integer for " + option + ": " + value);
}

inline std::runtime_error invalid_number(
    const std::string& value,
    const std::string& option) {
    return std::runtime_error("invalid number for " + option + ": " + value);
}

inline bool starts_with_negative_sign(const std::string& value) {
    const std::size_t first = value.find_first_not_of(" \t\n\r\f\v");
    return first != std::string::npos && value[first] == '-';
}

} // namespace detail

inline std::uint32_t parse_u32(
    const std::string& value,
    const std::string& option) {
    if (detail::starts_with_negative_sign(value)) {
        throw detail::invalid_integer(value, option);
    }
    try {
        std::size_t parsed = 0;
        const unsigned long result = std::stoul(value, &parsed, 10);
        if (parsed != value.size() ||
            result > (std::numeric_limits<std::uint32_t>::max)()) {
            throw detail::invalid_integer(value, option);
        }
        return static_cast<std::uint32_t>(result);
    }
    catch (const std::invalid_argument&) {
        throw detail::invalid_integer(value, option);
    }
    catch (const std::out_of_range&) {
        throw detail::invalid_integer(value, option);
    }
}

inline std::uint64_t parse_u64(
    const std::string& value,
    const std::string& option) {
    if (detail::starts_with_negative_sign(value)) {
        throw detail::invalid_integer(value, option);
    }
    try {
        std::size_t parsed = 0;
        const unsigned long long result = std::stoull(value, &parsed, 10);
        if (parsed != value.size() ||
            result > (std::numeric_limits<std::uint64_t>::max)()) {
            throw detail::invalid_integer(value, option);
        }
        return static_cast<std::uint64_t>(result);
    }
    catch (const std::invalid_argument&) {
        throw detail::invalid_integer(value, option);
    }
    catch (const std::out_of_range&) {
        throw detail::invalid_integer(value, option);
    }
}

inline int parse_int(
    const std::string& value,
    const std::string& option) {
    try {
        std::size_t parsed = 0;
        const long result = std::stol(value, &parsed, 10);
        if (parsed != value.size() ||
            result < (std::numeric_limits<int>::min)() ||
            result > (std::numeric_limits<int>::max)()) {
            throw detail::invalid_integer(value, option);
        }
        return static_cast<int>(result);
    }
    catch (const std::invalid_argument&) {
        throw detail::invalid_integer(value, option);
    }
    catch (const std::out_of_range&) {
        throw detail::invalid_integer(value, option);
    }
}

inline double parse_double(
    const std::string& value,
    const std::string& option) {
    try {
        std::size_t parsed = 0;
        const double result = std::stod(value, &parsed);
        if (parsed != value.size() || !std::isfinite(result)) {
            throw detail::invalid_number(value, option);
        }
        return result;
    }
    catch (const std::invalid_argument&) {
        throw detail::invalid_number(value, option);
    }
    catch (const std::out_of_range&) {
        throw detail::invalid_number(value, option);
    }
}

} // namespace qwen_tts_examples::cli
