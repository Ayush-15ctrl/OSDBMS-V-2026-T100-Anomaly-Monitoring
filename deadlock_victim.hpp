#pragma once

#include "deadlock.hpp"

#include <algorithm>
#include <stdexcept>
#include <vector>

namespace bams {

// Aborting the highest transaction id consistently rolls back the youngest transaction.
inline TransactionId choose_deadlock_victim(
    const std::vector<TransactionId>& cycle
) {
    if (cycle.empty()) {
        throw std::invalid_argument("cannot choose a victim from an empty cycle");
    }
    return *std::max_element(cycle.begin(), cycle.end());
}

}  // namespace bams
