// MERID EventBus - Authoritative implementation
import { validateEventPayload } from './validators.js';
import { rootReducer } from './reducers.js';
import { getValidator } from './stateValidator.js';
import { getState, setState } from './stateStore.js';
import { logError, logInfo } from '../utils/logger.js';

class EventBus {
    constructor() {
        this.subscribers = new Map();
        this.stateValidator = getValidator();
        logInfo('[MERID] EventBus initialized');
    }

    subscribe(eventType, callback) {
        if (!this.subscribers.has(eventType)) {
            this.subscribers.set(eventType, new Set());
        }
        this.subscribers.get(eventType).add(callback);
        return () => this.subscribers.get(eventType).delete(callback);
    }

    dispatch(event) {
        const { type, payload } = event;
        try {
            validateEventPayload(type, payload);
            const currentState = getState();
            const nextState = rootReducer(currentState, event);
            this.stateValidator(nextState);
            setState(nextState);
            this.notify(type, payload);
        } catch (error) {
            logError(`[MERID] Event dispatch failed for ${type}`, error);
            throw error;
        }
    }

    notify(eventType, payload) {
        const subscribers = this.subscribers.get(eventType);
        if (!subscribers) {
            return;
        }
        subscribers.forEach(cb => {
            try {
                cb(payload);
            } catch (error) {
                logError(`[MERID] Subscriber error for ${eventType}`, error);
            }
        });
    }
}

export const eventBus = new EventBus();
