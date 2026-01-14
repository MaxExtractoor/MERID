let currentState = null;

export function initializeState(initialState) {
    currentState = structuredClone(initialState);
}

export function getState() {
    if (currentState === null) {
        throw new Error('State accessed before initialization');
    }
    return currentState;
}

export function setState(nextState) {
    currentState = nextState;
}
