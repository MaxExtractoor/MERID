import axios from "axios";
import { API_BASE_URL } from "../config/constants";

const client = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true, // if using cookies
});

export default client;
