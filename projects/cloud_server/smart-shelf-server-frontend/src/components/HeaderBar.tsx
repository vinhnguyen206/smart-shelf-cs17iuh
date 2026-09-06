import React, { useEffect, useState } from "react";
import {
  AppBar,
  Toolbar,
  Typography,
  Box,
  Button,
  Snackbar,
  Alert,
  IconButton,
  Drawer,
  List,
  ListItem,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Divider,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import { useNavigate, useLocation } from "react-router-dom";
import { useSelector, useDispatch } from "react-redux";
import { RootState } from "../store";
import NotificationBell from "./NotificationBell";
import { logout } from "../store/user.actions";
import { 
  Dashboard,
  Menu as MenuIcon,
  Inventory,
  ShoppingCart,
  People,
  Assignment,
  Receipt,
  History,
  Image,
  Settings,
  Logout,
  Login,
  Close as CloseIcon,
} from "@mui/icons-material";
import SettingsIcon from "@mui/icons-material/Settings";

const HeaderBar: React.FC = () => {
  const [editingShelf, setEditingShelf] = useState<number | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [openNoAccess, setOpenNoAccess] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));

  const user = useSelector((state: RootState) => state.user.user);
  const isLoggedIn = Boolean(user);

  const dispatch = useDispatch();

  useEffect(() => {
    // nếu chưa đăng nhập => vào /login
    if (!isLoggedIn) {
      if (location.pathname !== "/login") navigate("/login");
      return;
    }

    // nếu đã login nhưng không phải admin/manager => show snackbar (không redirect)
    const role = (user?.role || "").toString().toLowerCase();
    const allowed = role === "admin" || role === "manager";
    if (!allowed) {
      setOpenNoAccess(true);
    }
  }, [isLoggedIn, user?.role, navigate, location.pathname]);

  const handleCloseNoAccess = (_?: any, reason?: string) => {
    if (reason === "clickaway") return;
    setOpenNoAccess(false);
  };

  const handleMenuOpen = (e: React.MouseEvent, id: number) => {
    setEditingShelf(id);
  };

  const handleNavigate = (path: string) => {
    navigate(path);
    setMobileMenuOpen(false);
  };

  const handleLogout = () => {
    dispatch(logout() as any);
    navigate("/login");
    setMobileMenuOpen(false);
  };

  const menuItems = [
    { text: "Dashboard", icon: <Dashboard />, path: "/" },
    { text: "Quản lý kệ", icon: <Inventory />, path: "/shelf" },
    { text: "Sản phẩm", icon: <ShoppingCart />, path: "/products" },
    { text: "Combo", icon: <ShoppingCart />, path: "/combo" },
    { text: "Hóa đơn", icon: <Receipt />, path: "/receipts" },
    { text: "Nhân sự", icon: <People />, path: "/users" },
    { text: "Lịch sử", icon: <History />, path: "/history" },
    { text: "Posters", icon: <Image />, path: "/posters" },
    { text: "Máy & Thẻ", icon: <Inventory />, path: "/machine" },
  ];

  return (
    <>
      <AppBar position="fixed">
        <Toolbar>
          {isMobile ? (
            // Mobile Navigation
            <>
              <IconButton
                color="inherit"
                edge="start"
                onClick={() => setMobileMenuOpen(true)}
                sx={{ mr: 2 }}
              >
                <MenuIcon />
              </IconButton>
              <Typography variant="h6" sx={{ flexGrow: 1, fontSize: '1rem' }}>
                Smart Shelf
              </Typography>
              {isLoggedIn && (
                <Box sx={{ display: 'flex', alignItems: 'center' }}>
                  <IconButton color="inherit" onClick={() => navigate("/config")} size="small">
                    <SettingsIcon fontSize="small" />
                  </IconButton>
                  <NotificationBell />
                </Box>
              )}
            </>
          ) : (
            // Desktop Navigation
            <Box sx={{ flexGrow: 1, display: "flex", alignItems: "center" }}>
              <Button color="inherit" onClick={() => navigate("/")} sx={{ ml: 2 }}>
                THỐNG KÊ
              </Button>
              <Button color="inherit" onClick={() => navigate("/shelf")} sx={{ ml: 2 }}>
                Quản lý kệ
              </Button>
              <Button color="inherit" onClick={() => navigate("/products")} sx={{ ml: 2 }}>
                Sản phẩm
              </Button>
              <Button color="inherit" onClick={() => navigate("/combo")} sx={{ ml: 2 }}>
                Combo
              </Button>
              <Button color="inherit" onClick={() => navigate("/receipts")} sx={{ ml: 2 }}>
                Hóa đơn
              </Button>
              <Button color="inherit" onClick={() => navigate("/users")} sx={{ ml: 2 }}>
                Nhân sự
              </Button>
              <Button color="inherit" onClick={() => navigate("/history")} sx={{ ml: 2 }}>
                Lịch sử
              </Button>
              <Button color="inherit" onClick={() => navigate("/posters")} sx={{ ml: 2 }}>
                Posters
              </Button>
              <Button color="inherit" onClick={() => navigate("/machine")} sx={{ ml: 2 }}>
                Máy & Thẻ
              </Button>

              <Box sx={{ ml: "auto" }}>
                {isLoggedIn ? (
                  <Box sx={{ display: "flex", alignItems: "center" }}>
                    <IconButton color="inherit" onClick={() => navigate("/config")} sx={{ mr: 1 }}>
                      <SettingsIcon />
                    </IconButton>
                    <NotificationBell />
                    <Typography>{user?.fullName}</Typography>
                    <Button
                      color="inherit"
                      onClick={() => {
                        dispatch(logout() as any);
                        navigate("/login");
                      }}
                      sx={{ ml: 2 }}
                    >
                      Đăng xuất
                    </Button>
                  </Box>
                ) : (
                  <Button color="inherit" onClick={() => navigate("/login")} sx={{ ml: 2 }}>
                    Đăng nhập
                  </Button>
                )}
              </Box>
            </Box>
          )}
        </Toolbar>
      </AppBar>

      {/* Mobile Drawer Menu */}
      <Drawer
        anchor="left"
        open={mobileMenuOpen}
        onClose={() => setMobileMenuOpen(false)}
      >
        <Box sx={{ width: 280 }}>
          {/* Close button */}
          <Box sx={{ display: 'flex', justifyContent: 'flex-end', p: 1 }}>
            <IconButton onClick={() => setMobileMenuOpen(false)} size="small">
              <CloseIcon />
            </IconButton>
          </Box>

          {isLoggedIn && (
            <>
              <Box sx={{ px: 2, pb: 2 }}>
                <Typography variant="h6" noWrap>
                  {user?.fullName}
                </Typography>
                <Typography variant="caption" color="textSecondary">
                  {user?.email}
                </Typography>
              </Box>
              <Divider />
            </>
          )}
          
          <List>
            {menuItems.map((item) => (
              <ListItem key={item.path} disablePadding>
                <ListItemButton
                  onClick={() => handleNavigate(item.path)}
                  selected={location.pathname === item.path}
                >
                  <ListItemIcon>{item.icon}</ListItemIcon>
                  <ListItemText primary={item.text} />
                </ListItemButton>
              </ListItem>
            ))}
          </List>

          <Divider />

          {isLoggedIn ? (
            <List>
              <ListItem disablePadding>
                <ListItemButton onClick={() => handleNavigate("/config")}>
                  <ListItemIcon><Settings /></ListItemIcon>
                  <ListItemText primary="Cài đặt" />
                </ListItemButton>
              </ListItem>
              <ListItem disablePadding>
                <ListItemButton onClick={handleLogout}>
                  <ListItemIcon><Logout /></ListItemIcon>
                  <ListItemText primary="Đăng xuất" />
                </ListItemButton>
              </ListItem>
            </List>
          ) : (
            <List>
              <ListItem disablePadding>
                <ListItemButton onClick={() => handleNavigate("/login")}>
                  <ListItemIcon><Login /></ListItemIcon>
                  <ListItemText primary="Đăng nhập" />
                </ListItemButton>
              </ListItem>
            </List>
          )}
        </Box>
      </Drawer>

      <Snackbar
        open={openNoAccess}
        autoHideDuration={4000}
        onClose={handleCloseNoAccess}
        anchorOrigin={{ vertical: "top", horizontal: "center" }}
      >
        <Alert onClose={handleCloseNoAccess} severity="error" sx={{ width: "100%" }}>
          Bạn không có quyền truy cập
        </Alert>
      </Snackbar>

      <Box sx={{ pt: isMobile ? "56px" : "64px" }} />
    </>
  );
};

export default HeaderBar;
